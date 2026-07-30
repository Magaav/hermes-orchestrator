package studio

import (
	"errors"
	"net/http"

	"visao/backend/internal/auth"
)

func (h *Handler) UsageDashboard(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication_required", "Faça login para continuar.")
		return
	}
	if h.usage == nil {
		writeError(w, http.StatusServiceUnavailable, "studio_usage_unavailable", "O painel do Studio está indisponível.")
		return
	}
	result, err := h.usage.Dashboard(
		r.Context(),
		user,
		r.URL.Query().Get("period"),
		r.URL.Query().Get("scope"),
		r.URL.Query().Get("anchor"),
	)
	if err != nil {
		if errors.Is(err, contextInvalidAnchor) {
			writeError(w, http.StatusBadRequest, "invalid_anchor", "A data do painel é inválida.")
			return
		}
		writeError(w, http.StatusInternalServerError, "studio_usage_failed", "Não foi possível carregar o uso do Studio.")
		return
	}
	writeJSON(w, http.StatusOK, result)
}
