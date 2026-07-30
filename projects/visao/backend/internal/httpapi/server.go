package httpapi

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"visao/backend/internal/auth"
	"visao/backend/internal/config"
	"visao/backend/internal/control"
	"visao/backend/internal/studio"
	"visao/backend/internal/submissions"
)

var validID = regexp.MustCompile(`^[a-f0-9]{24}$`)

type Server struct {
	cfg         config.Config
	store       *submissions.Store
	auth        *auth.Manager
	control     *control.Store
	controlHTTP *control.HTTP
	studio      *studio.Handler
	buildID     string
}

func New(cfg config.Config, store *submissions.Store, buildID string) (*Server, error) {
	authManager, err := auth.New(context.Background(), cfg, store.Connection())
	if err != nil {
		return nil, err
	}
	controlStore, err := control.New(context.Background(), store.Connection(), cfg)
	if err != nil {
		return nil, err
	}
	usageStore, err := studio.NewUsageStore(context.Background(), store.Connection(), cfg.Location)
	if err != nil {
		return nil, err
	}
	sessionStore, err := studio.NewSessionStore(context.Background(), store.Connection(), cfg.StudioSessionsDir, cfg.Location)
	if err != nil {
		return nil, err
	}
	studioHandler := studio.New(studio.Config{
		PythonBin: cfg.StudioPythonBin, WorkerScript: cfg.StudioWorkerScript, CodexScript: cfg.StudioCodexScript,
		Usage: usageStore, Sessions: sessionStore, Audit: controlStore,
	})
	return &Server{
		cfg: cfg, store: store, auth: authManager, control: controlStore,
		controlHTTP: control.NewHTTP(controlStore), studio: studioHandler, buildID: buildID,
	}, nil
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.health)
	mux.HandleFunc("GET /readyz", s.ready)
	mux.HandleFunc("GET /api/version", s.version)
	mux.HandleFunc("GET /api/session", s.session)
	mux.HandleFunc("DELETE /api/session", s.logout)
	mux.HandleFunc("GET /auth/google/start", s.auth.StartGoogle)
	mux.HandleFunc("GET /auth/google/callback", s.auth.Callback)
	mux.Handle("GET /api/schema", s.requireCapability(control.CapWorkspaceView, http.HandlerFunc(s.schema)))
	mux.Handle("GET /api/submissions", s.requireCapability(control.CapAtendimentoView, http.HandlerFunc(s.listSubmissions)))
	mux.Handle("POST /api/submissions", s.requireCapability(control.CapAtendimentoWrite, s.requireSameOrigin(http.HandlerFunc(s.saveSubmission))))
	mux.Handle("GET /api/submissions/{id}", s.requireCapability(control.CapAtendimentoView, http.HandlerFunc(s.getSubmission)))
	mux.Handle("GET /api/submissions/{id}/documents", s.requireCapability(control.CapAtendimentoView, http.HandlerFunc(s.downloadSubmissionDocuments)))
	mux.Handle("POST /api/uploads", s.requireCapability(control.CapAtendimentoWrite, s.requireSameOrigin(http.HandlerFunc(s.upload))))
	mux.Handle("GET /api/uploads/{id}", s.requireCapability(control.CapAtendimentoView, http.HandlerFunc(s.download)))
	mux.Handle("GET /api/studio/status", s.requireCapability(control.CapStudioView, http.HandlerFunc(s.studio.Status)))
	mux.Handle("GET /api/studio/usage", s.requireCapability(control.CapStudioDashboard, http.HandlerFunc(s.studio.UsageDashboard)))
	mux.Handle("GET /api/studio/sessions", s.requireCapability(control.CapStudioSessions, http.HandlerFunc(s.studio.ListSessions)))
	mux.Handle("POST /api/studio/sessions", s.requireCapability(control.CapStudioSessions, s.requireSameOrigin(http.HandlerFunc(s.studio.CreateSession))))
	mux.Handle("GET /api/studio/sessions/{sessionID}", s.requireCapability(control.CapStudioSessions, http.HandlerFunc(s.studio.GetSession)))
	mux.Handle("DELETE /api/studio/sessions/{sessionID}", s.requireCapability(control.CapStudioSessions, s.requireSameOrigin(http.HandlerFunc(s.studio.DeleteSession))))
	mux.Handle("POST /api/studio/sessions/{sessionID}/photos", s.requireCapability(control.CapStudioSessions, s.requireSameOrigin(http.HandlerFunc(s.studio.SaveSessionPhoto))))
	mux.Handle("GET /api/studio/sessions/{sessionID}/photos/{photoID}/{kind}", s.requireCapability(control.CapStudioSessions, http.HandlerFunc(s.studio.SessionPhoto)))
	mux.Handle("POST /api/studio/login/start", s.requireCapability(control.CapStudioSettings, s.requireSameOrigin(http.HandlerFunc(s.studio.StartLogin))))
	mux.Handle("POST /api/studio/clean", s.requireCapability(control.CapStudioClean, s.requireSameOrigin(s.studio)))
	mux.Handle("GET /api/settings/preferences", s.requireCapability(control.CapSettingsView, http.HandlerFunc(s.controlHTTP.Preferences)))
	mux.Handle("PUT /api/settings/preferences", s.requireCapability(control.CapSettingsPreferences, s.requireSameOrigin(http.HandlerFunc(s.controlHTTP.Preferences))))
	mux.Handle("GET /api/settings/inventory", s.requireCapability(control.CapSettingsInventory, http.HandlerFunc(s.controlHTTP.Inventory)))
	mux.Handle("GET /api/settings/audit", s.requireCapability(control.CapSettingsAudit, http.HandlerFunc(s.controlHTTP.Audit)))
	mux.Handle("GET /api/settings/admin", s.requireCapability(control.CapSettingsAdmin, http.HandlerFunc(s.controlHTTP.Admin)))
	mux.Handle("POST /api/settings/admin/roles", s.requireCapability(control.CapAdminRolesManage, s.requireSameOrigin(http.HandlerFunc(s.controlHTTP.Roles))))
	mux.Handle("PUT /api/settings/admin/roles/{roleID}", s.requireCapability(control.CapAdminRolesManage, s.requireSameOrigin(http.HandlerFunc(s.controlHTTP.Roles))))
	mux.Handle("DELETE /api/settings/admin/roles/{roleID}", s.requireCapability(control.CapAdminRolesManage, s.requireSameOrigin(http.HandlerFunc(s.controlHTTP.Roles))))
	mux.Handle("PUT /api/settings/admin/roles/{roleID}/actions", s.requireCapability(control.CapAdminActionsManage, s.requireSameOrigin(http.HandlerFunc(s.controlHTTP.RoleActions))))
	mux.Handle("POST /api/settings/admin/users", s.requireCapability(control.CapAdminUsersInvite, s.requireSameOrigin(http.HandlerFunc(s.controlHTTP.Users))))
	mux.Handle("PUT /api/settings/admin/users/{email}", s.requireCapability(control.CapAdminRolesAssign, s.requireSameOrigin(http.HandlerFunc(s.controlHTTP.Users))))
	mux.Handle("DELETE /api/settings/admin/users/{email}", s.requireCapability(control.CapAdminUsersRevoke, s.requireSameOrigin(http.HandlerFunc(s.controlHTTP.Users))))
	mux.Handle("GET /api/profile/picture/{userID}", s.requireCapability(control.CapProfileView, http.HandlerFunc(s.controlHTTP.ProfilePicture)))
	mux.Handle("PUT /api/profile/picture", s.requireCapability(control.CapProfileUpdate, s.requireSameOrigin(http.HandlerFunc(s.controlHTTP.SaveProfilePicture))))
	mux.HandleFunc("/", s.frontend)
	return s.securityHeaders(mux)
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	if err := s.store.Ready(r.Context()); err != nil {
		writeError(w, http.StatusServiceUnavailable, "database_not_ready", "Banco de dados indisponível.", nil)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
}

func (s *Server) version(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"app": s.cfg.AppName, "build": s.buildID, "domain": s.cfg.PublicBaseURL,
		"auth":         s.auth.Status(),
		"capabilities": []string{"google_oauth", "authenticated_form", "draft_autosave", "pdf_upload", "sqlite_persistence", "print_view", "studio_batch_cleaner", "studio_usage_dashboard", "studio_session_history", "workspace_preferences", "storage_inventory", "cud_audit", "role_based_access"},
	})
}

func (s *Server) schema(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"v": 1,
		"resources": map[string]any{
			"submission": map[string]any{
				"states":  []string{"draft", "submitted"},
				"actions": []string{"list", "get", "save", "submit", "print"},
				"proof":   []string{"id", "status", "updatedAt", "submittedAt"},
			},
			"upload": map[string]any{"accept": []string{"application/pdf"}, "maxBytes": 20 << 20},
			"studio": map[string]any{
				"actions":   []string{"select", "status", "login", "clean", "compare", "usage", "create_session", "list_sessions", "open_session", "delete_session", "export"},
				"accept":    []string{"image/jpeg", "image/png", "image/webp", "image/avif"},
				"maxPhotos": studio.MaxPhotos, "maxImageBytes": studio.MaxSourceBytes, "workerLanes": 10,
				"states": []string{"ready", "queued", "cleaning", "cleaned", "failed"},
				"transport": map[string]string{
					"schema": "visao.studio.master_frontier.envelope.v1",
					"model":  "master:frontier",
					"owner":  "visao",
				},
				"proof": []string{"accountState", "runtimeState", "datacenterState", "sessionId", "photoId", "elapsedMs", "traceId", "model", "providerModel", "state", "progress", "outputType", "outputBytes", "usageComplete", "totalTokens"},
				"usage": map[string]any{
					"scopes":  []string{"me", "all"},
					"periods": []string{"day", "month", "year"},
					"source":  "provider_reported_partial",
				},
			},
			"control": map[string]any{
				"actions":      []string{"preferences", "inventory", "audit", "roles", "users"},
				"capabilities": control.Capabilities,
				"audit": map[string]any{
					"actions": []string{"create", "update", "delete"},
					"fields":  []string{"date", "user", "type", "table", "recordId", "reason", "json"},
				},
			},
		},
	})
}

func (s *Server) session(w http.ResponseWriter, r *http.Request) {
	user, err := s.auth.CurrentUser(r)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"authenticated": false, "user": nil, "auth": s.auth.Status()})
		return
	}
	if err := s.control.Enrich(r.Context(), user); err != nil {
		writeError(w, http.StatusInternalServerError, "access_failed", "Não foi possível carregar suas permissões.", nil)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"authenticated": true, "user": user, "auth": s.auth.Status()})
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	if !sameOrigin(r) {
		writeError(w, http.StatusForbidden, "origin_rejected", "Origem da requisição não permitida.", nil)
		return
	}
	s.auth.Logout(w, r)
	writeJSON(w, http.StatusOK, map[string]bool{"authenticated": false})
}

func (s *Server) listSubmissions(w http.ResponseWriter, r *http.Request) {
	items, err := s.store.List(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "list_failed", "Não foi possível listar os atendimentos.", nil)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "count": len(items)})
}

func (s *Server) getSubmission(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if !validID.MatchString(id) {
		writeError(w, http.StatusBadRequest, "invalid_id", "Atendimento inválido.", nil)
		return
	}
	item, err := s.store.Get(r.Context(), id)
	if errors.Is(err, submissions.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "Atendimento não encontrado.", nil)
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "read_failed", "Não foi possível abrir o atendimento.", nil)
		return
	}
	writeJSON(w, http.StatusOK, item)
}

func (s *Server) saveSubmission(w http.ResponseWriter, r *http.Request) {
	if !sameOrigin(r) {
		writeError(w, http.StatusForbidden, "origin_rejected", "Origem da requisição não permitida.", nil)
		return
	}
	var body struct {
		ID      string          `json:"id"`
		Status  string          `json:"status"`
		Payload json.RawMessage `json:"payload"`
	}
	if err := decodeJSON(r, &body, 1<<20); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_payload", "Dados do formulário inválidos.", nil)
		return
	}
	if body.ID != "" && !validID.MatchString(body.ID) {
		writeError(w, http.StatusBadRequest, "invalid_id", "Atendimento inválido.", nil)
		return
	}
	values, missing, err := payloadValues(body.Payload)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_payload", "Dados do formulário inválidos.", nil)
		return
	}
	if body.Status == "submitted" && len(missing) > 0 {
		writeError(w, http.StatusUnprocessableEntity, "required_fields", "Revise os campos obrigatórios antes de enviar.", missing)
		return
	}
	item, err := s.store.Save(r.Context(), submissions.Submission{
		ID: body.ID, Status: body.Status, Atendimento: values["meta.atendimento"], Corretor: values["meta.corretor"], Payload: body.Payload,
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "save_failed", "Não foi possível salvar o atendimento.", nil)
		return
	}
	user, _ := auth.UserFromContext(r.Context())
	action := "update"
	if body.ID == "" {
		action = "create"
	}
	_ = s.control.Audit(r.Context(), user, action, "submissions", item.ID, "Atendimento salvo", map[string]any{
		"id": item.ID, "status": item.Status, "atendimento": item.Atendimento,
	})
	writeJSON(w, http.StatusOK, item)
}

func (s *Server) upload(w http.ResponseWriter, r *http.Request) {
	if !sameOrigin(r) {
		writeError(w, http.StatusForbidden, "origin_rejected", "Origem da requisição não permitida.", nil)
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 20<<20)
	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "upload_missing", "Selecione um arquivo PDF de até 20 MB.", nil)
		return
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, (20<<20)+1))
	if err != nil || len(data) > 20<<20 || len(data) < 5 || string(data[:5]) != "%PDF-" {
		writeError(w, http.StatusBadRequest, "invalid_pdf", "O arquivo deve ser um PDF válido de até 20 MB.", nil)
		return
	}
	if err := os.MkdirAll(s.cfg.UploadsDir, 0o750); err != nil {
		writeError(w, http.StatusInternalServerError, "upload_failed", "Não foi possível preparar o armazenamento.", nil)
		return
	}
	id := randomID()
	if err := os.WriteFile(filepath.Join(s.cfg.UploadsDir, id+".pdf"), data, 0o640); err != nil {
		writeError(w, http.StatusInternalServerError, "upload_failed", "Não foi possível salvar o documento.", nil)
		return
	}
	user, _ := auth.UserFromContext(r.Context())
	_ = s.control.Audit(r.Context(), user, "create", "uploads", id, "Documento anexado", map[string]any{
		"id": id, "name": safeFileName(header.Filename), "size": len(data), "contentType": "application/pdf",
	})
	writeJSON(w, http.StatusCreated, map[string]any{
		"id": id, "name": safeFileName(header.Filename), "size": len(data), "contentType": "application/pdf", "url": "/api/uploads/" + id,
	})
}

func (s *Server) download(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if !validID.MatchString(id) {
		http.NotFound(w, r)
		return
	}
	path := filepath.Join(s.cfg.UploadsDir, id+".pdf")
	if _, err := os.Stat(path); err != nil {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "application/pdf")
	disposition := "inline"
	if r.URL.Query().Get("download") == "1" {
		disposition = "attachment"
	}
	w.Header().Set("Content-Disposition", fmt.Sprintf(`%s; filename="documento-%s.pdf"`, disposition, id))
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Set("X-Frame-Options", "SAMEORIGIN")
	w.Header().Set("Content-Security-Policy", "frame-ancestors 'self'")
	http.ServeFile(w, r, path)
}

func (s *Server) downloadSubmissionDocuments(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if !validID.MatchString(id) {
		http.NotFound(w, r)
		return
	}
	files, err := s.store.Documents(r.Context(), id, s.cfg.UploadsDir)
	if err != nil {
		switch {
		case errors.Is(err, submissions.ErrNotFound):
			http.NotFound(w, r)
		case errors.Is(err, submissions.ErrNoDocuments):
			writeError(w, http.StatusUnprocessableEntity, "documents_empty", "Este atendimento ainda não possui documentos.", nil)
		case errors.Is(err, submissions.ErrDocumentMissing):
			writeError(w, http.StatusConflict, "document_missing", "Um documento deste atendimento não está disponível.", nil)
		default:
			writeError(w, http.StatusInternalServerError, "documents_failed", "Não foi possível preparar os documentos.", nil)
		}
		return
	}
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="atendimento-%s-documentos.zip"`, id))
	w.Header().Set("Cache-Control", "private, no-store")
	if err := submissions.WriteDocumentsZIP(w, files); err != nil {
		return
	}
}

func (s *Server) frontend(w http.ResponseWriter, r *http.Request) {
	path := filepath.Clean(strings.TrimPrefix(r.URL.Path, "/"))
	if path == ".." || strings.HasPrefix(path, ".."+string(filepath.Separator)) || filepath.IsAbs(path) {
		http.NotFound(w, r)
		return
	}
	if path == "." {
		path = "index.html"
	}
	filePath := filepath.Join(s.cfg.FrontendDist, path)
	if info, err := os.Stat(filePath); err != nil || info.IsDir() {
		filePath = filepath.Join(s.cfg.FrontendDist, "index.html")
		path = "index.html"
	}
	if path == "index.html" || strings.HasSuffix(path, ".webmanifest") || path == "sw.js" {
		w.Header().Set("Cache-Control", "no-store, max-age=0")
	} else if strings.HasPrefix(path, "assets/") {
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
	}
	http.ServeFile(w, r, filePath)
}

func (s *Server) requireAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		user, err := s.auth.CurrentUser(r)
		if err != nil {
			writeError(w, http.StatusUnauthorized, "authentication_required", "Faça login para continuar.", nil)
			return
		}
		if err := s.control.Enrich(r.Context(), user); err != nil {
			writeError(w, http.StatusInternalServerError, "access_failed", "Não foi possível carregar suas permissões.", nil)
			return
		}
		next.ServeHTTP(w, r.WithContext(auth.WithUser(r.Context(), user)))
	})
}

func (s *Server) requireCapability(capability string, next http.Handler) http.Handler {
	return s.requireAuth(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		user, _ := auth.UserFromContext(r.Context())
		allowed := false
		for _, current := range user.Capabilities {
			if current == capability {
				allowed = true
				break
			}
		}
		if !allowed {
			writeError(w, http.StatusForbidden, "permission_denied", "Você não tem permissão para esta ação.", nil)
			return
		}
		next.ServeHTTP(w, r)
	}))
}

func (s *Server) requireSameOrigin(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !sameOrigin(r) {
			writeError(w, http.StatusForbidden, "origin_rejected", "Origem da requisição não permitida.", nil)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "same-origin")
		w.Header().Set("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self'; img-src 'self' https://lh3.googleusercontent.com data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
		if strings.HasPrefix(r.URL.Path, "/api/") || strings.HasPrefix(r.URL.Path, "/auth/") {
			w.Header().Set("Cache-Control", "no-store")
		}
		next.ServeHTTP(w, r)
	})
}

func payloadValues(payload json.RawMessage) (map[string]string, []string, error) {
	var form struct {
		Values map[string]string `json:"values"`
	}
	if err := json.Unmarshal(payload, &form); err != nil || form.Values == nil {
		return nil, nil, fmt.Errorf("invalid form payload")
	}
	required := []string{"meta.date", "meta.atendimento", "meta.corretor", "property.ref", "property.value", "property.address", "buyer.name", "buyer.cpf", "buyer.email", "seller.name", "seller.cpf", "deal.totalValue"}
	missing := make([]string, 0)
	for _, key := range required {
		if strings.TrimSpace(form.Values[key]) == "" {
			missing = append(missing, key)
		}
	}
	return form.Values, missing, nil
}

func decodeJSON(r *http.Request, target any, limit int64) error {
	defer r.Body.Close()
	decoder := json.NewDecoder(io.LimitReader(r.Body, limit+1))
	decoder.DisallowUnknownFields()
	return decoder.Decode(target)
}

func sameOrigin(r *http.Request) bool {
	origin := r.Header.Get("Origin")
	if origin == "" {
		return true
	}
	parsed, err := url.Parse(origin)
	return err == nil && strings.EqualFold(parsed.Host, r.Host)
}

func randomID() string {
	data := make([]byte, 12)
	if _, err := rand.Read(data); err != nil {
		panic(err)
	}
	return hex.EncodeToString(data)
}

func safeFileName(value string) string {
	value = filepath.Base(strings.TrimSpace(value))
	value = strings.Map(func(r rune) rune {
		if r < 32 || r == '"' || r == '\\' || r == '/' {
			return -1
		}
		return r
	}, value)
	if value == "" {
		return "documento.pdf"
	}
	if ext := strings.ToLower(filepath.Ext(value)); ext != ".pdf" {
		value = strings.TrimSuffix(value, filepath.Ext(value)) + ".pdf"
	}
	return value
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, status int, code, message string, fields []string) {
	writeJSON(w, status, map[string]any{"error": code, "message": message, "fields": fields})
}
