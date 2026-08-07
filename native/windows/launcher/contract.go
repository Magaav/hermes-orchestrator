package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
)

const supervisorSchema = "hermes.wasm_agent.windows_supervisor.v1"

var supervisorCapabilities = []string{
	"capabilities.describe",
	"process.start",
	"process.stop",
	"process.restart",
	"process.status",
	"update.activate",
}

type commandPayload struct {
	InstallerPath   string `json:"installerPath,omitempty"`
	SHA256          string `json:"sha256,omitempty"`
	ExpectedBuildID string `json:"expectedBuildId,omitempty"`
}

func updateInstallerArgsForRoot(installRoot string, programRoots ...string) []string {
	mode := "/currentuser"
	for _, root := range programRoots {
		if root != "" && pathWithin(root, installRoot) {
			mode = "/allusers"
			break
		}
	}
	return []string{"/S", mode}
}

func installedBuildID(installRoot string) (string, error) {
	data, err := os.ReadFile(filepath.Join(installRoot, "resources", "native-defaults.json"))
	if err != nil {
		return "", errors.New("installed_build_metadata_missing")
	}
	var metadata struct {
		BuildID string `json:"buildId"`
	}
	if json.Unmarshal(data, &metadata) != nil || strings.TrimSpace(metadata.BuildID) == "" {
		return "", errors.New("installed_build_metadata_invalid")
	}
	return metadata.BuildID, nil
}

func verifyInstalledBuild(installRoot, expectedBuildID string) error {
	if strings.TrimSpace(expectedBuildID) == "" {
		return errors.New("expected_build_id_missing")
	}
	observedBuildID, err := installedBuildID(installRoot)
	if err != nil {
		return err
	}
	if observedBuildID != expectedBuildID {
		return errors.New("installed_build_mismatch")
	}
	return nil
}

type supervisorCommand struct {
	Schema  string         `json:"schema"`
	ID      string         `json:"id"`
	Type    string         `json:"type"`
	Payload commandPayload `json:"payload"`
}

func normalizeSHA256(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	if len(value) != 64 {
		return ""
	}
	for _, char := range value {
		if !strings.ContainsRune("0123456789abcdef", char) {
			return ""
		}
	}
	return value
}

func pathWithin(root, candidate string) bool {
	rootAbs, rootErr := filepath.Abs(root)
	candidateAbs, candidateErr := filepath.Abs(candidate)
	if rootErr != nil || candidateErr != nil {
		return false
	}
	relative, err := filepath.Rel(rootAbs, candidateAbs)
	return err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(os.PathSeparator))
}

func validateInstaller(stagingRoot string, payload commandPayload) error {
	if !pathWithin(stagingRoot, payload.InstallerPath) {
		return errors.New("installer_path_denied")
	}
	if !strings.EqualFold(filepath.Ext(payload.InstallerPath), ".exe") {
		return errors.New("installer_type_denied")
	}
	expected := normalizeSHA256(payload.SHA256)
	if expected == "" {
		return errors.New("installer_hash_required")
	}
	file, err := os.Open(payload.InstallerPath)
	if err != nil {
		return errors.New("installer_missing")
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return errors.New("installer_hash_failed")
	}
	if hex.EncodeToString(hash.Sum(nil)) != expected {
		return errors.New("installer_hash_mismatch")
	}
	return nil
}
