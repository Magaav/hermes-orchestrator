package config

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	AppName               string
	AppEnv                string
	PublicBaseURL         string
	HTTPBind              string
	HTTPPort              string
	DBPath                string
	UploadsDir            string
	FrontendDist          string
	StudioPythonBin       string
	StudioWorkerScript    string
	StudioCodexScript     string
	StudioSessionsDir     string
	ProfilePicturesDir    string
	GoogleCredentialsFile string
	GoogleClientID        string
	GoogleClientSecret    string
	GoogleRedirectURL     string
	AuthAllowedEmails     []string
	AuthAllowAllGoogle    bool
	AccessOwnerEmail      string
	SessionSecret         string
	SecureCookies         bool
	ProjectRoot           string
	Location              *time.Location
}

func Load(path string) (Config, error) {
	if path == "" {
		path = firstNonEmpty(os.Getenv("APP_ENV_FILE"), "/local/projects/visao/app.env")
	}
	values, err := readEnv(path)
	if err != nil {
		return Config{}, err
	}
	lookup := func(key, fallback string) string {
		if value := os.Getenv(key); value != "" {
			return value
		}
		if value, ok := values[key]; ok {
			return value
		}
		return fallback
	}
	root := filepath.Clean(lookup("PROJECT_ROOT", filepath.Dir(path)))
	credentialsFile := lookup("GOOGLE_CREDENTIALS_FILE", "")
	credentials := map[string]string{}
	if credentialsFile != "" {
		credentials, err = readEnv(credentialsFile)
		if err != nil {
			return Config{}, fmt.Errorf("load Google credentials: %w", err)
		}
	}
	googleLookup := func(key string) string {
		if value := os.Getenv(key); value != "" {
			return value
		}
		if value := values[key]; value != "" {
			return value
		}
		return credentials[key]
	}
	location, err := time.LoadLocation(lookup("APP_TIMEZONE", "America/Sao_Paulo"))
	if err != nil {
		return Config{}, fmt.Errorf("load timezone: %w", err)
	}
	cfg := Config{
		AppName:               lookup("APP_NAME", "Visão Vendas"),
		AppEnv:                lookup("APP_ENV", "production"),
		PublicBaseURL:         lookup("APP_PUBLIC_BASE_URL", "https://visao.colmeio.com"),
		HTTPBind:              lookup("HTTP_BIND", "127.0.0.1"),
		HTTPPort:              lookup("HTTP_PORT", "18083"),
		DBPath:                lookup("DB_PATH", filepath.Join(root, "data", "visao.sqlite3")),
		UploadsDir:            lookup("UPLOADS_DIR", filepath.Join(root, "data", "uploads")),
		FrontendDist:          lookup("FRONTEND_DIST", filepath.Join(root, "frontend", "dist")),
		StudioPythonBin:       lookup("STUDIO_PYTHON_BIN", "python3"),
		StudioWorkerScript:    lookup("STUDIO_WORKER_SCRIPT", filepath.Join(root, "backend", "studio_worker.py")),
		StudioCodexScript:     lookup("STUDIO_CODEX_SCRIPT", filepath.Join(root, "backend", "studio_codex.py")),
		StudioSessionsDir:     lookup("STUDIO_SESSIONS_DIR", filepath.Join(root, "data", "studio-sessions")),
		ProfilePicturesDir:    lookup("PROFILE_PICTURES_DIR", filepath.Join(root, "data", "profile-pictures")),
		GoogleCredentialsFile: credentialsFile,
		GoogleClientID:        googleLookup("GOOGLE_CLIENT_ID"),
		GoogleClientSecret:    googleLookup("GOOGLE_CLIENT_SECRET"),
		GoogleRedirectURL:     lookup("GOOGLE_REDIRECT_URL", "https://visao.colmeio.com/auth/google/callback"),
		AuthAllowedEmails:     splitCSV(lookup("AUTH_ALLOWED_EMAILS", "")),
		AuthAllowAllGoogle:    parseBool(lookup("AUTH_ALLOW_ALL_GOOGLE_EMAILS", "false")),
		AccessOwnerEmail:      strings.ToLower(strings.TrimSpace(lookup("ACCESS_OWNER_EMAIL", ""))),
		SessionSecret:         lookup("SESSION_SECRET", ""),
		SecureCookies:         parseBool(lookup("SECURE_COOKIES", "true")),
		ProjectRoot:           root,
		Location:              location,
	}
	if cfg.GoogleClientID == "" || cfg.GoogleClientSecret == "" || cfg.GoogleRedirectURL == "" {
		return Config{}, fmt.Errorf("Google OAuth requires GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URL")
	}
	if !cfg.AuthAllowAllGoogle && len(cfg.AuthAllowedEmails) == 0 {
		return Config{}, fmt.Errorf("AUTH_ALLOWED_EMAILS is required unless AUTH_ALLOW_ALL_GOOGLE_EMAILS is true")
	}
	if cfg.AccessOwnerEmail == "" && len(cfg.AuthAllowedEmails) > 0 {
		cfg.AccessOwnerEmail = cfg.AuthAllowedEmails[0]
	}
	if len(cfg.SessionSecret) < 32 {
		return Config{}, fmt.Errorf("SESSION_SECRET must contain at least 32 characters")
	}
	return cfg, nil
}

func (c Config) Addr() string { return c.HTTPBind + ":" + c.HTTPPort }

func readEnv(path string) (map[string]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open env file %s: %w", path, err)
	}
	defer file.Close()
	values := map[string]string{}
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		values[strings.TrimSpace(key)] = strings.Trim(strings.TrimSpace(value), `"`)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return values, nil
}

func parseBool(value string) bool {
	parsed, err := strconv.ParseBool(value)
	return err == nil && parsed
}

func splitCSV(value string) []string {
	items := []string{}
	for _, item := range strings.Split(value, ",") {
		item = strings.ToLower(strings.TrimSpace(item))
		if item != "" {
			items = append(items, item)
		}
	}
	return items
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}
