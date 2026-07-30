package control

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"visao/backend/internal/auth"
)

const maxProfilePictureBytes = 5 << 20

type ProfilePicture struct {
	Path      string
	MediaType string
}

func (s *Store) SaveProfilePicture(ctx context.Context, user *auth.User, data []byte) (string, error) {
	if user == nil || user.ID <= 0 || len(data) == 0 || len(data) > maxProfilePictureBytes {
		return "", errors.New("invalid profile picture")
	}
	mediaType := http.DetectContentType(data)
	switch mediaType {
	case "image/jpeg", "image/png", "image/webp":
	default:
		return "", errors.New("unsupported profile picture")
	}
	if err := os.MkdirAll(s.cfg.ProfilePicturesDir, 0o750); err != nil {
		return "", err
	}
	target := filepath.Join(s.cfg.ProfilePicturesDir, strconv.FormatInt(user.ID, 10)+".profile")
	file, err := os.CreateTemp(s.cfg.ProfilePicturesDir, fmt.Sprintf(".profile-%d-*", user.ID))
	if err != nil {
		return "", err
	}
	tempPath := file.Name()
	defer os.Remove(tempPath)
	if err := file.Chmod(0o640); err != nil {
		file.Close()
		return "", err
	}
	if _, err := file.Write(data); err != nil {
		file.Close()
		return "", err
	}
	if err := file.Close(); err != nil {
		return "", err
	}
	if err := os.Rename(tempPath, target); err != nil {
		return "", err
	}
	picture := fmt.Sprintf("/api/profile/picture/%d?v=%d", user.ID, time.Now().UnixMilli())
	if _, err := s.db.ExecContext(ctx, `UPDATE users SET custom_picture = ? WHERE id = ?`, picture, user.ID); err != nil {
		return "", err
	}
	_ = s.Audit(ctx, user, "update", "users", strconv.FormatInt(user.ID, 10), "Foto de perfil atualizada", map[string]any{
		"userId": user.ID, "mediaType": mediaType, "bytes": len(data),
	})
	return picture, nil
}

func (s *Store) ProfilePicture(userID int64) (ProfilePicture, error) {
	if userID <= 0 {
		return ProfilePicture{}, os.ErrNotExist
	}
	path := filepath.Join(s.cfg.ProfilePicturesDir, strconv.FormatInt(userID, 10)+".profile")
	data, err := os.ReadFile(path)
	if err != nil {
		return ProfilePicture{}, err
	}
	mediaType := http.DetectContentType(data)
	switch mediaType {
	case "image/jpeg", "image/png", "image/webp":
	default:
		return ProfilePicture{}, os.ErrNotExist
	}
	return ProfilePicture{Path: path, MediaType: mediaType}, nil
}
