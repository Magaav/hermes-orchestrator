package main

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
)

func TestValidateInstaller(t *testing.T) {
	root := t.TempDir()
	installer := filepath.Join(root, "WASM-Agent-Setup.exe")
	contents := []byte("verified installer fixture")
	if err := os.WriteFile(installer, contents, 0600); err != nil {
		t.Fatal(err)
	}
	hash := sha256.Sum256(contents)
	payload := commandPayload{InstallerPath: installer, SHA256: hex.EncodeToString(hash[:])}
	if err := validateInstaller(root, payload); err != nil {
		t.Fatalf("expected valid installer: %v", err)
	}
	payload.SHA256 = "0" + payload.SHA256[1:]
	if err := validateInstaller(root, payload); err == nil {
		t.Fatal("expected hash mismatch")
	}
	payload.InstallerPath = filepath.Join(root, "..", "outside.exe")
	if err := validateInstaller(root, payload); err == nil {
		t.Fatal("expected path denial")
	}
}

func TestCapabilityContract(t *testing.T) {
	if supervisorSchema != "hermes.wasm_agent.windows_supervisor.v1" {
		t.Fatalf("unexpected schema %q", supervisorSchema)
	}
	if len(supervisorCapabilities) < 5 {
		t.Fatalf("capability surface unexpectedly small: %v", supervisorCapabilities)
	}
}

func TestUpdateInstallerModeIsExplicit(t *testing.T) {
	root := t.TempDir()
	programFiles := filepath.Join(root, "Program Files")
	userInstall := filepath.Join(root, "Users", "Victor", "AppData", "Local", "Programs", "WASM Agent")
	userArgs := updateInstallerArgsForRoot(userInstall, programFiles)
	if len(userArgs) != 2 || userArgs[0] != "/S" || userArgs[1] != "/currentuser" {
		t.Fatalf("per-user update must be silent and explicit: %v", userArgs)
	}
	machineArgs := updateInstallerArgsForRoot(filepath.Join(programFiles, "WASM Agent"), programFiles)
	if len(machineArgs) != 2 || machineArgs[1] != "/allusers" {
		t.Fatalf("machine update must request one explicit elevation path: %v", machineArgs)
	}
}

func TestInstalledBuildMustMatchBeforeRestart(t *testing.T) {
	root := t.TempDir()
	resources := filepath.Join(root, "resources")
	if err := os.MkdirAll(resources, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(resources, "native-defaults.json"), []byte(`{"buildId":"win-x64-20260803T010203Z"}`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := verifyInstalledBuild(root, "win-x64-20260803T010203Z"); err != nil {
		t.Fatalf("expected installed build match: %v", err)
	}
	if err := verifyInstalledBuild(root, "win-x64-20260803T020304Z"); err == nil || err.Error() != "installed_build_mismatch" {
		t.Fatalf("expected installed build mismatch, got %v", err)
	}
}
