package httpapi

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestSecurityHeadersAllowBrowserLocalImagePreviews(t *testing.T) {
	server := &Server{}
	handler := server.securityHeaders(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}))
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "https://visao.colmeio.com/", nil))

	csp := response.Header().Get("Content-Security-Policy")
	if !strings.Contains(csp, "img-src 'self' https://lh3.googleusercontent.com data: blob:") {
		t.Fatalf("image preview sources missing from CSP: %s", csp)
	}
	if !strings.Contains(csp, "script-src 'self' 'wasm-unsafe-eval'") ||
		!strings.Contains(csp, "worker-src 'self'") ||
		strings.Contains(csp, "'unsafe-eval'") {
		t.Fatalf("bounded AVIF worker sources missing from CSP: %s", csp)
	}
}
