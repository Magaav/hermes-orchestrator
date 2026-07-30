package studio

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"strings"
	"time"

	"visao/backend/internal/auth"
)

const (
	MaxPhotos          = 50
	MaxSourceBytes     = 20 << 20
	maxRequestBytes    = 28 << 20
	workerLanes        = 10
	studioWriteTimeout = 4 * time.Minute
)

type Config struct {
	PythonBin    string
	WorkerScript string
	CodexScript  string
	Usage        *UsageStore
	Sessions     *SessionStore
	Audit        Auditor
}

type Auditor interface {
	Audit(context.Context, *auth.User, string, string, string, string, any) error
}

type workerJob struct {
	output io.ReadCloser
	wait   func() error
}

type workerStarter func(context.Context, []byte) (*workerJob, error)

type Handler struct {
	slots    chan struct{}
	start    workerStarter
	codex    codexControl
	usage    *UsageStore
	sessions *SessionStore
	audit    Auditor
}

func New(cfg Config) *Handler {
	handler := &Handler{
		slots:    make(chan struct{}, workerLanes),
		codex:    newCodexManager(cfg.PythonBin, cfg.CodexScript),
		usage:    cfg.Usage,
		sessions: cfg.Sessions,
		audit:    cfg.Audit,
	}
	handler.start = commandStarter(cfg)
	return handler
}

func (h *Handler) Status(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, h.codex.Status(r.Context()))
}

func (h *Handler) StartLogin(w http.ResponseWriter, r *http.Request) {
	if !sameOrigin(r) {
		writeError(w, http.StatusForbidden, "origin_rejected", "Origem da requisição não permitida.")
		return
	}
	login, err := h.codex.StartLogin(r.Context())
	if err != nil {
		writeError(w, http.StatusBadGateway, "codex_login_unavailable", "Não foi possível iniciar o acesso ao Codex.")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"login": login})
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	controller := http.NewResponseController(w)
	_ = controller.SetWriteDeadline(time.Now().Add(studioWriteTimeout))
	defer func() { _ = controller.SetWriteDeadline(time.Time{}) }()

	if !sameOrigin(r) {
		writeError(w, http.StatusForbidden, "origin_rejected", "Origem da requisição não permitida.")
		return
	}
	if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
		writeError(w, http.StatusUnsupportedMediaType, "invalid_content_type", "Envie a foto como JSON.")
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, maxRequestBytes)
	payload, err := io.ReadAll(r.Body)
	if err != nil {
		writeError(w, http.StatusRequestEntityTooLarge, "image_too_large", "A foto deve ter no máximo 20 MB.")
		return
	}
	var request struct {
		CloudConsent        bool   `json:"cloud_consent"`
		WatermarkAuthorized bool   `json:"watermark_authorized"`
		MediaType           string `json:"media_type"`
		ImageBase64         string `json:"image_base64"`
	}
	if json.Unmarshal(payload, &request) != nil || !request.CloudConsent || request.ImageBase64 == "" {
		writeError(w, http.StatusBadRequest, "invalid_request", "A foto e a autorização de processamento são obrigatórias.")
		return
	}
	switch strings.ToLower(request.MediaType) {
	case "image/jpeg", "image/png", "image/webp", "image/avif":
	default:
		writeError(w, http.StatusBadRequest, "unsupported_image", "Use uma imagem JPEG, PNG, WebP ou AVIF.")
		return
	}
	select {
	case h.slots <- struct{}{}:
		defer func() { <-h.slots }()
	case <-r.Context().Done():
		return
	}

	job, err := h.start(r.Context(), payload)
	if err != nil {
		writeError(w, http.StatusBadGateway, "studio_worker_unavailable", "O Studio não conseguiu iniciar o tratamento.")
		return
	}
	defer job.output.Close()

	w.Header().Set("Content-Type", "application/x-ndjson; charset=utf-8")
	w.Header().Set("Content-Encoding", "identity")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
	buffer := make([]byte, 64<<10)
	streamBytes := 0
	terminalSeen := false
	usageCapture := newUsageCapture()
	for {
		count, readErr := job.output.Read(buffer)
		if count > 0 {
			streamBytes += count
			usageCapture.Write(buffer[:count])
			terminalSeen = terminalSeen ||
				bytes.Contains(buffer[:count], []byte(`"event":"complete"`)) ||
				bytes.Contains(buffer[:count], []byte(`"event":"error"`))
			if _, writeErr := w.Write(buffer[:count]); writeErr != nil {
				log.Printf("Studio stream write failed after %d bytes: %T", streamBytes, writeErr)
				_ = job.output.Close()
				_ = job.wait()
				return
			}
			if flushErr := controller.Flush(); flushErr != nil {
				log.Printf("Studio stream flush failed after %d bytes: %T", streamBytes, flushErr)
				_ = job.output.Close()
				_ = job.wait()
				return
			}
		}
		if readErr != nil {
			if !errors.Is(readErr, io.EOF) {
				log.Printf("Studio stream read failed after %d bytes: %T", streamBytes, readErr)
			}
			break
		}
	}
	if waitErr := job.wait(); waitErr != nil {
		log.Printf("Studio worker exited without a valid terminal frame: %v", waitErr)
		frame, _ := json.Marshal(map[string]any{
			"event": "error",
			"detail": map[string]string{
				"code":    "studio_worker_exited",
				"message": "O Studio interrompeu o tratamento antes de gerar a imagem.",
			},
		})
		_, _ = w.Write(append(frame, '\n'))
		_ = controller.Flush()
		return
	}
	if !terminalSeen {
		log.Printf("Studio worker closed after %d bytes without a terminal frame", streamBytes)
		frame, _ := json.Marshal(map[string]any{
			"event": "error",
			"detail": map[string]string{
				"code":    "studio_terminal_missing",
				"message": "O Studio encerrou o tratamento sem confirmar a imagem.",
			},
		})
		_, _ = w.Write(append(frame, '\n'))
		_ = controller.Flush()
		return
	}
	if h.usage != nil {
		if user, ok := auth.UserFromContext(r.Context()); ok {
			if record, ok := usageCapture.Record(user); ok {
				if err := h.usage.Record(r.Context(), record); err != nil {
					log.Printf("Studio usage persistence failed: %T", err)
				} else if h.audit != nil {
					_ = h.audit.Audit(r.Context(), user, "create", "studio_usage", record.TraceID, "Tratamento de imagem concluído", map[string]any{
						"traceId": record.TraceID, "sourceName": record.SourceName,
						"providerModel": record.ProviderModel, "totalTokens": record.Usage.TotalTokens,
						"usageComplete": record.Usage.Complete,
					})
				}
			}
		}
	}
}

func commandStarter(cfg Config) workerStarter {
	return func(ctx context.Context, payload []byte) (*workerJob, error) {
		command := exec.CommandContext(ctx, cfg.PythonBin, cfg.WorkerScript)
		command.Stdin = bytes.NewReader(payload)
		command.Env = os.Environ()
		var stderr bytes.Buffer
		command.Stderr = &stderr
		output, err := command.StdoutPipe()
		if err != nil {
			return nil, err
		}
		if err := command.Start(); err != nil {
			return nil, fmt.Errorf("start Studio worker: %w", err)
		}
		return &workerJob{
			output: output,
			wait: func() error {
				if err := command.Wait(); err != nil {
					return fmt.Errorf("Studio worker failed: %w: %s", err, strings.TrimSpace(stderr.String()))
				}
				return nil
			},
		}, nil
	}
}

func sameOrigin(r *http.Request) bool {
	origin := r.Header.Get("Origin")
	if origin == "" {
		return true
	}
	parsed, err := url.Parse(origin)
	return err == nil && strings.EqualFold(parsed.Host, r.Host)
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"error":   code,
		"message": message,
	})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
