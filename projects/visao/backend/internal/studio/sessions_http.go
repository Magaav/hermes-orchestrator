package studio

import (
	"errors"
	"mime"
	"net/http"
	"strconv"
	"strings"

	"visao/backend/internal/auth"
)

const maxSessionUploadBytes = 54 << 20

func (h *Handler) ListSessions(w http.ResponseWriter, r *http.Request) {
	user, ok := sessionUser(w, r)
	if !ok {
		return
	}
	if h.sessions == nil {
		writeError(w, http.StatusServiceUnavailable, "studio_sessions_unavailable", "O histórico do Studio está indisponível.")
		return
	}
	items, err := h.sessions.List(r.Context(), user.ID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "studio_sessions_failed", "Não foi possível carregar as sessões.")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "count": len(items)})
}

func (h *Handler) CreateSession(w http.ResponseWriter, r *http.Request) {
	user, ok := sessionMutationUser(w, r)
	if !ok {
		return
	}
	if h.sessions == nil {
		writeError(w, http.StatusServiceUnavailable, "studio_sessions_unavailable", "O histórico do Studio está indisponível.")
		return
	}
	session, err := h.sessions.Create(r.Context(), user.ID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "studio_session_create_failed", "Não foi possível criar a sessão.")
		return
	}
	if h.audit != nil {
		_ = h.audit.Audit(r.Context(), user, "create", "studio_sessions", session.ID, "Sessão do Studio criada", map[string]any{"id": session.ID})
	}
	writeJSON(w, http.StatusCreated, session)
}

func (h *Handler) GetSession(w http.ResponseWriter, r *http.Request) {
	user, ok := sessionUser(w, r)
	if !ok {
		return
	}
	if h.sessions == nil {
		writeError(w, http.StatusServiceUnavailable, "studio_sessions_unavailable", "O histórico do Studio está indisponível.")
		return
	}
	session, err := h.sessions.Get(r.Context(), user.ID, r.PathValue("sessionID"))
	if errors.Is(err, ErrSessionNotFound) {
		writeError(w, http.StatusNotFound, "studio_session_not_found", "Sessão não encontrada.")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "studio_session_failed", "Não foi possível abrir a sessão.")
		return
	}
	writeJSON(w, http.StatusOK, session)
}

func (h *Handler) DeleteSession(w http.ResponseWriter, r *http.Request) {
	user, ok := sessionMutationUser(w, r)
	if !ok {
		return
	}
	if h.sessions == nil {
		writeError(w, http.StatusServiceUnavailable, "studio_sessions_unavailable", "O histórico do Studio está indisponível.")
		return
	}
	err := h.sessions.Delete(r.Context(), user.ID, r.PathValue("sessionID"))
	if errors.Is(err, ErrSessionNotFound) {
		writeError(w, http.StatusNotFound, "studio_session_not_found", "Sessão não encontrada.")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "studio_session_delete_failed", "Não foi possível excluir a sessão.")
		return
	}
	if h.audit != nil {
		_ = h.audit.Audit(r.Context(), user, "delete", "studio_sessions", r.PathValue("sessionID"), "Sessão do Studio excluída", map[string]any{"id": r.PathValue("sessionID")})
	}
	writeJSON(w, http.StatusOK, map[string]bool{"deleted": true})
}

func (h *Handler) SaveSessionPhoto(w http.ResponseWriter, r *http.Request) {
	user, ok := sessionMutationUser(w, r)
	if !ok {
		return
	}
	if h.sessions == nil {
		writeError(w, http.StatusServiceUnavailable, "studio_sessions_unavailable", "O histórico do Studio está indisponível.")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxSessionUploadBytes)
	if err := r.ParseMultipartForm(2 << 20); err != nil {
		writeError(w, http.StatusRequestEntityTooLarge, "studio_session_photo_too_large", "Os arquivos da foto excedem o limite da sessão.")
		return
	}
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	source, sourceHeader, err := r.FormFile("source")
	if err != nil {
		writeError(w, http.StatusBadRequest, "studio_session_source_missing", "A foto original é obrigatória.")
		return
	}
	defer source.Close()
	output, outputHeader, err := r.FormFile("output")
	if err != nil {
		writeError(w, http.StatusBadRequest, "studio_session_output_missing", "A foto AVIF tratada é obrigatória.")
		return
	}
	defer output.Close()
	sourceType := strings.ToLower(sourceHeader.Header.Get("Content-Type"))
	outputType := strings.ToLower(outputHeader.Header.Get("Content-Type"))
	if !sessionSourceType(sourceType) || outputType != "image/avif" {
		writeError(w, http.StatusBadRequest, "studio_session_image_invalid", "Use uma origem compatível e uma saída AVIF.")
		return
	}
	elapsedMS, _ := strconv.ParseInt(r.FormValue("elapsedMs"), 10, 64)
	photo, err := h.sessions.AddPhoto(r.Context(), user.ID, r.PathValue("sessionID"), SaveSessionPhoto{
		TraceID:    r.FormValue("traceId"),
		SourceName: sourceHeader.Filename,
		SourceType: sourceType,
		OutputType: outputType,
		ElapsedMS:  elapsedMS,
		Source:     source,
		Output:     output,
	})
	if errors.Is(err, ErrSessionNotFound) {
		writeError(w, http.StatusNotFound, "studio_session_not_found", "Sessão ou tratamento não encontrado.")
		return
	}
	if errors.Is(err, ErrSessionFull) {
		writeError(w, http.StatusConflict, "studio_session_full", "Esta sessão já possui 50 fotos.")
		return
	}
	if err != nil {
		writeError(w, http.StatusUnprocessableEntity, "studio_session_photo_failed", "Não foi possível arquivar esta foto.")
		return
	}
	if h.audit != nil {
		_ = h.audit.Audit(r.Context(), user, "create", "studio_session_photos", photo.ID, "Foto arquivada na sessão", map[string]any{
			"id": photo.ID, "sessionId": r.PathValue("sessionID"), "sourceName": photo.SourceName,
			"outputType": photo.OutputType, "elapsedMs": photo.ElapsedMS,
		})
	}
	writeJSON(w, http.StatusCreated, photo)
}

func (h *Handler) SessionPhoto(w http.ResponseWriter, r *http.Request) {
	user, ok := sessionUser(w, r)
	if !ok {
		return
	}
	if h.sessions == nil {
		http.NotFound(w, r)
		return
	}
	file, err := h.sessions.File(
		r.Context(),
		user.ID,
		r.PathValue("sessionID"),
		r.PathValue("photoID"),
		r.PathValue("kind"),
	)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	disposition := mime.FormatMediaType("inline", map[string]string{"filename": file.Name})
	w.Header().Set("Content-Type", file.MediaType)
	w.Header().Set("Content-Disposition", disposition)
	w.Header().Set("Cache-Control", "private, no-store")
	http.ServeFile(w, r, file.Path)
}

func sessionUser(w http.ResponseWriter, r *http.Request) (*auth.User, bool) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication_required", "Faça login para continuar.")
		return nil, false
	}
	return user, true
}

func sessionMutationUser(w http.ResponseWriter, r *http.Request) (*auth.User, bool) {
	user, ok := sessionUser(w, r)
	if !ok {
		return nil, false
	}
	if !sameOrigin(r) {
		writeError(w, http.StatusForbidden, "origin_rejected", "Origem da requisição não permitida.")
		return nil, false
	}
	return user, true
}

func sessionSourceType(value string) bool {
	switch value {
	case "image/jpeg", "image/png", "image/webp", "image/avif":
		return true
	default:
		return false
	}
}
