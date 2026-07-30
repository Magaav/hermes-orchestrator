package studio

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type fakeCodexControl struct {
	status AccessStatus
	login  LoginStatus
	err    error
}

func (f fakeCodexControl) Status(context.Context) AccessStatus {
	return f.status
}

func (f fakeCodexControl) StartLogin(context.Context) (LoginStatus, error) {
	return f.login, f.err
}

func validRequest() string {
	return `{"cloud_consent":true,"watermark_authorized":false,"media_type":"image/jpeg","image_base64":"aW1hZ2U="}`
}

func TestHandlerStreamsWorkerFrames(t *testing.T) {
	handler := &Handler{
		slots: make(chan struct{}, workerLanes),
		start: func(_ context.Context, _ []byte) (*workerJob, error) {
			return &workerJob{
				output: io.NopCloser(strings.NewReader("{\"event\":\"accepted\"}\n{\"event\":\"complete\"}\n")),
				wait:   func() error { return nil },
			}, nil
		},
	}
	request := httptest.NewRequest(http.MethodPost, "https://visao.colmeio.com/api/studio/clean", strings.NewReader(validRequest()))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Origin", "https://visao.colmeio.com")
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", response.Code)
	}
	if got := response.Header().Get("Content-Type"); !strings.Contains(got, "application/x-ndjson") {
		t.Fatalf("unexpected content type %q", got)
	}
	if got := response.Header().Get("Content-Encoding"); got != "identity" {
		t.Fatalf("Studio stream must bypass proxy compression, got %q", got)
	}
	if !strings.Contains(response.Body.String(), `"event":"complete"`) {
		t.Fatalf("missing completion frame: %s", response.Body.String())
	}
}

func TestHandlerTurnsWorkerExitIntoTypedTerminalFrame(t *testing.T) {
	handler := &Handler{
		slots: make(chan struct{}, workerLanes),
		start: func(_ context.Context, _ []byte) (*workerJob, error) {
			return &workerJob{
				output: io.NopCloser(strings.NewReader("{\"event\":\"accepted\"}\n")),
				wait:   func() error { return errors.New("private worker detail") },
			}, nil
		},
	}
	request := httptest.NewRequest(http.MethodPost, "https://visao.colmeio.com/api/studio/clean", strings.NewReader(validRequest()))
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	body := response.Body.String()
	if !strings.Contains(body, `"code":"studio_worker_exited"`) {
		t.Fatalf("missing typed worker-exit frame: %s", body)
	}
	if strings.Contains(body, "private worker detail") {
		t.Fatalf("worker stderr leaked to client: %s", body)
	}
}

func TestHandlerRejectsForeignOrigin(t *testing.T) {
	handler := New(Config{PythonBin: "python3"})
	request := httptest.NewRequest(http.MethodPost, "https://visao.colmeio.com/api/studio/clean", strings.NewReader(validRequest()))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Origin", "https://example.com")
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	if response.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", response.Code)
	}
}

func TestHandlerRejectsUnsupportedImagesBeforeStartingWorker(t *testing.T) {
	handler := New(Config{PythonBin: "python3"})
	request := httptest.NewRequest(http.MethodPost, "https://visao.colmeio.com/api/studio/clean", strings.NewReader(
		`{"cloud_consent":true,"media_type":"image/gif","image_base64":"aW1hZ2U="}`,
	))
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", response.Code)
	}
}

func TestStatusReturnsCompactRedactedDatacenterProof(t *testing.T) {
	expected := AccessStatus{
		Account:    AccountStatus{State: "connected", AuthMode: "chatgpt", PlanType: "plus"},
		Runtime:    RuntimeStatus{State: "ready"},
		Datacenter: DatacenterStatus{State: "ready"},
		Login:      LoginStatus{State: "idle"},
		CheckedAt:  "2026-07-30T12:00:00Z",
	}
	handler := &Handler{codex: fakeCodexControl{status: expected}}
	request := httptest.NewRequest(http.MethodGet, "https://visao.colmeio.com/api/studio/status", nil)
	response := httptest.NewRecorder()

	handler.Status(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", response.Code)
	}
	var payload AccessStatus
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.Datacenter.State != "ready" || payload.Account.AuthMode != "chatgpt" {
		t.Fatalf("unexpected status: %#v", payload)
	}
	if strings.Contains(response.Body.String(), "token") || strings.Contains(response.Body.String(), "email") {
		t.Fatalf("status must remain redacted: %s", response.Body.String())
	}
}

func TestStartLoginReturnsOnlyDeviceCeremony(t *testing.T) {
	handler := &Handler{codex: fakeCodexControl{login: LoginStatus{
		State: "pending", VerificationURL: "https://auth.openai.com/codex/device", UserCode: "ABCD-1234",
	}}}
	request := httptest.NewRequest(http.MethodPost, "https://visao.colmeio.com/api/studio/login/start", strings.NewReader("{}"))
	request.Header.Set("Origin", "https://visao.colmeio.com")
	response := httptest.NewRecorder()

	handler.StartLogin(response, request)

	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"userCode":"ABCD-1234"`) {
		t.Fatalf("unexpected login response: code=%d body=%s", response.Code, response.Body.String())
	}
}

func TestStartLoginRejectsForeignOriginAndRuntimeFailure(t *testing.T) {
	handler := &Handler{codex: fakeCodexControl{err: errors.New("raw-internal-detail")}}
	foreign := httptest.NewRequest(http.MethodPost, "https://visao.colmeio.com/api/studio/login/start", strings.NewReader("{}"))
	foreign.Header.Set("Origin", "https://example.test")
	foreignResponse := httptest.NewRecorder()
	handler.StartLogin(foreignResponse, foreign)
	if foreignResponse.Code != http.StatusForbidden {
		t.Fatalf("expected foreign origin rejection, got %d", foreignResponse.Code)
	}

	local := httptest.NewRequest(http.MethodPost, "https://visao.colmeio.com/api/studio/login/start", strings.NewReader("{}"))
	local.Header.Set("Origin", "https://visao.colmeio.com")
	localResponse := httptest.NewRecorder()
	handler.StartLogin(localResponse, local)
	if localResponse.Code != http.StatusBadGateway || strings.Contains(localResponse.Body.String(), "raw-internal-detail") {
		t.Fatalf("runtime detail must be hidden: code=%d body=%s", localResponse.Code, localResponse.Body.String())
	}
}
