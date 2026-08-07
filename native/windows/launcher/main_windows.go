//go:build windows

package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"
)

const (
	mutexName          = "Local\\WASMAgentNativeSupervisor"
	errorAlreadyExists = syscall.Errno(183)
)

type supervisorStatus struct {
	Schema       string   `json:"schema"`
	OK           bool     `json:"ok"`
	PID          int      `json:"pid"`
	ChildPID     int      `json:"childPid"`
	State        string   `json:"state"`
	Capabilities []string `json:"capabilities"`
	UpdatedAt    string   `json:"updatedAt"`
}

type commandResult struct {
	Schema          string `json:"schema"`
	OK              bool   `json:"ok"`
	CommandID       string `json:"commandId"`
	Action          string `json:"action"`
	Error           string `json:"error,omitempty"`
	ExpectedBuildID string `json:"expectedBuildId,omitempty"`
	UpdatedAt       string `json:"updatedAt"`
}

type supervisor struct {
	root       string
	stateRoot  string
	commandDir string
	resultDir  string
	child      *exec.Cmd
}

type updateHandoff struct {
	Schema      string            `json:"schema"`
	Command     supervisorCommand `json:"command"`
	InstallRoot string            `json:"installRoot"`
	StateRoot   string            `json:"stateRoot"`
}

type updateTimeline struct {
	Schema          string `json:"schema"`
	Phase           string `json:"phase"`
	CommandID       string `json:"commandId"`
	ExpectedBuildID string `json:"expectedBuildId"`
	ObservedBuildID string `json:"observedBuildId,omitempty"`
	InstallMode     string `json:"installMode,omitempty"`
	InstallerExit   int    `json:"installerExitCode,omitempty"`
	Failure         string `json:"failure,omitempty"`
	StartedAt       string `json:"startedAt"`
	UpdatedAt       string `json:"updatedAt"`
}

func writeUpdateTimeline(stateRoot string, timeline updateTimeline) {
	timeline.Schema = "hermes.wasm_agent.windows_update_timeline.v1"
	timeline.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	_ = writeJSONAtomic(filepath.Join(stateRoot, "update-timeline.json"), timeline)
}

func writeJSONAtomic(target string, payload any) error {
	if err := os.MkdirAll(filepath.Dir(target), 0700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return err
	}
	temporary := target + ".tmp"
	if err := os.WriteFile(temporary, append(data, '\n'), 0600); err != nil {
		return err
	}
	_ = os.Remove(target)
	return os.Rename(temporary, target)
}

func acquireSingleInstance() (syscall.Handle, error) {
	name, err := syscall.UTF16PtrFromString(mutexName)
	if err != nil {
		return 0, err
	}
	handle, _, callErr := syscall.NewLazyDLL("kernel32.dll").NewProc("CreateMutexW").Call(0, 0, uintptr(unsafe.Pointer(name)))
	if handle == 0 {
		return 0, callErr
	}
	if callErr == errorAlreadyExists {
		syscall.CloseHandle(syscall.Handle(handle))
		return 0, errors.New("supervisor_already_running")
	}
	return syscall.Handle(handle), nil
}

func installRoot() (string, error) {
	executable, err := os.Executable()
	if err != nil {
		return "", err
	}
	root := filepath.Dir(executable)
	if filepath.Base(root) == "resources" {
		root = filepath.Dir(root)
	}
	return root, nil
}

func newSupervisor(root string) (*supervisor, error) {
	localAppData := os.Getenv("LOCALAPPDATA")
	if localAppData == "" {
		return nil, errors.New("local_app_data_missing")
	}
	stateRoot := filepath.Join(localAppData, "WASM Agent Native", "supervisor")
	return &supervisor{
		root:       root,
		stateRoot:  stateRoot,
		commandDir: filepath.Join(stateRoot, "commands"),
		resultDir:  filepath.Join(stateRoot, "results"),
	}, nil
}

func (item *supervisor) status(state string) supervisorStatus {
	childPID := 0
	if item.child != nil && item.child.Process != nil {
		childPID = item.child.Process.Pid
	}
	return supervisorStatus{Schema: supervisorSchema, OK: true, PID: os.Getpid(), ChildPID: childPID, State: state, Capabilities: supervisorCapabilities, UpdatedAt: time.Now().UTC().Format(time.RFC3339)}
}

func (item *supervisor) writeStatus(state string) {
	_ = writeJSONAtomic(filepath.Join(item.stateRoot, "status.json"), item.status(state))
}

func (item *supervisor) startChild() error {
	executable := filepath.Join(item.root, "WASM Agent.exe")
	if _, err := os.Stat(executable); err != nil {
		return errors.New("electron_executable_missing")
	}
	child := exec.Command(executable)
	child.Dir = item.root
	child.Env = append(os.Environ(), "WASM_AGENT_SUPERVISED=1", "WASM_AGENT_SUPERVISOR_STATE_DIR="+item.stateRoot)
	if err := child.Start(); err != nil {
		return err
	}
	item.child = child
	go func(active *exec.Cmd) {
		_ = active.Wait()
		if item.child == active {
			item.child = nil
			item.writeStatus("child_exited")
		}
	}(child)
	item.writeStatus("running")
	return nil
}

func (item *supervisor) stopChild() {
	if item.child != nil && item.child.Process != nil {
		_ = item.child.Process.Kill()
		item.child = nil
	}
}

func (item *supervisor) result(command supervisorCommand, ok bool, action, failure string) {
	_ = writeJSONAtomic(filepath.Join(item.resultDir, command.ID+".json"), commandResult{
		Schema: supervisorSchema, OK: ok, CommandID: command.ID, Action: action, Error: failure,
		ExpectedBuildID: command.Payload.ExpectedBuildID, UpdatedAt: time.Now().UTC().Format(time.RFC3339),
	})
}

func (item *supervisor) launchUpdateRunner(command supervisorCommand) error {
	current, err := os.Executable()
	if err != nil {
		return err
	}
	runnerDir := filepath.Join(item.stateRoot, "updater")
	if err := os.MkdirAll(runnerDir, 0700); err != nil {
		return err
	}
	runner := filepath.Join(runnerDir, "wasm-agent-update-runner.exe")
	data, err := os.ReadFile(current)
	if err != nil {
		return err
	}
	if err := os.WriteFile(runner, data, 0700); err != nil {
		return err
	}
	handoffPath := filepath.Join(runnerDir, "handoff.json")
	if err := writeJSONAtomic(handoffPath, updateHandoff{Schema: supervisorSchema, Command: command, InstallRoot: item.root, StateRoot: item.stateRoot}); err != nil {
		return err
	}
	process := exec.Command(runner, "--apply-update", handoffPath)
	process.Dir = runnerDir
	return process.Start()
}

func runUpdateHandoff(handoffPath string) int {
	data, err := os.ReadFile(handoffPath)
	if err != nil {
		return 2
	}
	var handoff updateHandoff
	if json.Unmarshal(data, &handoff) != nil || handoff.Schema != supervisorSchema {
		return 2
	}
	stagingRoot := filepath.Join(filepath.Dir(handoff.StateRoot), "staged", "windows-updates")
	if validateInstaller(stagingRoot, handoff.Command.Payload) != nil {
		return 3
	}
	startedAt := time.Now().UTC().Format(time.RFC3339)
	timeline := updateTimeline{Phase: "handoff_validated", CommandID: handoff.Command.ID, ExpectedBuildID: handoff.Command.Payload.ExpectedBuildID, StartedAt: startedAt}
	writeUpdateTimeline(handoff.StateRoot, timeline)
	time.Sleep(1200 * time.Millisecond)
	installerArgs := updateInstallerArgsForRoot(handoff.InstallRoot, os.Getenv("ProgramFiles"), os.Getenv("ProgramFiles(x86)"))
	if len(installerArgs) > 1 {
		timeline.InstallMode = installerArgs[1]
	}
	timeline.Phase = "installer_started"
	writeUpdateTimeline(handoff.StateRoot, timeline)
	installer := exec.Command(handoff.Command.Payload.InstallerPath, installerArgs...)
	installer.Dir = filepath.Dir(handoff.Command.Payload.InstallerPath)
	installErr := installer.Run()
	if exitError, ok := installErr.(*exec.ExitError); ok {
		timeline.InstallerExit = exitError.ExitCode()
	}
	timeline.Phase = "installer_finished"
	writeUpdateTimeline(handoff.StateRoot, timeline)
	var installedBuildErr error
	if installErr == nil {
		installedBuildErr = verifyInstalledBuild(handoff.InstallRoot, handoff.Command.Payload.ExpectedBuildID)
		timeline.ObservedBuildID, _ = installedBuildID(handoff.InstallRoot)
	}
	var restartErr error
	if installErr == nil && installedBuildErr == nil {
		launcher := filepath.Join(handoff.InstallRoot, "resources", "wasm-agent-launcher.exe")
		restartErr = exec.Command(launcher).Start()
	}
	ok := installErr == nil && installedBuildErr == nil && restartErr == nil
	failure := ""
	if installErr != nil {
		failure = "installer_failed"
	} else if installedBuildErr != nil {
		failure = installedBuildErr.Error()
	} else if restartErr != nil {
		failure = "supervisor_restart_failed"
	}
	timeline.Failure = failure
	if ok {
		timeline.Phase = "relaunch_started"
	} else {
		timeline.Phase = "failed"
	}
	writeUpdateTimeline(handoff.StateRoot, timeline)
	_ = writeJSONAtomic(filepath.Join(handoff.StateRoot, "results", handoff.Command.ID+".json"), commandResult{Schema: supervisorSchema, OK: ok, CommandID: handoff.Command.ID, Action: "install_update_finished", Error: failure, ExpectedBuildID: handoff.Command.Payload.ExpectedBuildID, UpdatedAt: time.Now().UTC().Format(time.RFC3339)})
	if ok {
		return 0
	}
	return 4
}

func (item *supervisor) handle(command supervisorCommand) bool {
	switch command.Type {
	case "status":
		item.result(command, true, "status", "")
	case "restart":
		item.stopChild()
		if err := item.startChild(); err != nil {
			item.result(command, false, "restart", err.Error())
		} else {
			item.result(command, true, "restart", "")
		}
	case "stop":
		item.result(command, true, "stop", "")
		item.stopChild()
		return false
	case "install_update":
		stagingRoot := filepath.Join(filepath.Dir(item.stateRoot), "staged", "windows-updates")
		if err := validateInstaller(stagingRoot, command.Payload); err != nil {
			item.result(command, false, "install_update", err.Error())
			break
		}
		if err := item.launchUpdateRunner(command); err != nil {
			item.result(command, false, "install_update", "update_runner_launch_failed")
			break
		}
		item.result(command, true, "install_update_accepted", "")
		item.stopChild()
		item.writeStatus("installer_handoff")
		return false
	default:
		item.result(command, false, command.Type, "unsupported_command")
	}
	return true
}

func (item *supervisor) poll() bool {
	entries, _ := os.ReadDir(item.commandDir)
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".json" {
			continue
		}
		commandPath := filepath.Join(item.commandDir, entry.Name())
		data, err := os.ReadFile(commandPath)
		if err != nil {
			continue
		}
		var command supervisorCommand
		if json.Unmarshal(data, &command) != nil || command.ID == "" {
			_ = os.Remove(commandPath)
			continue
		}
		_ = os.Remove(commandPath)
		if !item.handle(command) {
			return false
		}
	}
	return true
}

func main() {
	if len(os.Args) == 3 && os.Args[1] == "--apply-update" {
		os.Exit(runUpdateHandoff(os.Args[2]))
	}
	handle, err := acquireSingleInstance()
	if err != nil {
		return
	}
	defer syscall.CloseHandle(handle)
	root, err := installRoot()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return
	}
	supervisor, err := newSupervisor(root)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return
	}
	_ = os.MkdirAll(supervisor.commandDir, 0700)
	_ = os.MkdirAll(supervisor.resultDir, 0700)
	if err := supervisor.startChild(); err != nil {
		supervisor.writeStatus(err.Error())
		return
	}
	for supervisor.poll() {
		time.Sleep(250 * time.Millisecond)
	}
}
