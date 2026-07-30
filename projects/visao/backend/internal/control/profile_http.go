package control

import (
	"io"
	"net/http"
	"strconv"

	"visao/backend/internal/auth"
)

func (h *HTTP) SaveProfilePicture(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok {
		controlError(w, http.StatusUnauthorized, "authentication_required", "Faça login para continuar.")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxProfilePictureBytes+(1<<20))
	file, _, err := r.FormFile("picture")
	if err != nil {
		controlError(w, http.StatusBadRequest, "picture_missing", "Selecione uma imagem de até 5 MB.")
		return
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, maxProfilePictureBytes+1))
	if err != nil || len(data) > maxProfilePictureBytes {
		controlError(w, http.StatusBadRequest, "picture_too_large", "A imagem deve ter até 5 MB.")
		return
	}
	picture, err := h.store.SaveProfilePicture(r.Context(), user, data)
	if err != nil {
		controlError(w, http.StatusBadRequest, "picture_invalid", "Use uma imagem JPEG, PNG ou WebP válida.")
		return
	}
	controlJSON(w, http.StatusOK, map[string]string{"picture": picture})
}

func (h *HTTP) ProfilePicture(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok {
		http.NotFound(w, r)
		return
	}
	userID, err := strconv.ParseInt(r.PathValue("userID"), 10, 64)
	if err != nil || (userID != user.ID && !h.store.Allowed(r.Context(), user.Email, CapSettingsAdmin)) {
		http.NotFound(w, r)
		return
	}
	picture, err := h.store.ProfilePicture(userID)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", picture.MediaType)
	w.Header().Set("Cache-Control", "private, max-age=86400")
	http.ServeFile(w, r, picture.Path)
}
