package studio

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"sync"
	"time"
)

const (
	statusTimeout = 25 * time.Second
	loginTimeout  = 10 * time.Minute
	maxFrameBytes = 64 << 10
)

type AccountStatus struct {
	State    string `json:"state"`
	AuthMode string `json:"authMode,omitempty"`
	PlanType string `json:"planType,omitempty"`
}

type RuntimeStatus struct {
	State      string `json:"state"`
	ErrorClass string `json:"errorClass,omitempty"`
}

type DatacenterStatus struct {
	State string `json:"state"`
}

type LoginStatus struct {
	State           string `json:"state"`
	VerificationURL string `json:"verificationUrl,omitempty"`
	UserCode        string `json:"userCode,omitempty"`
	Message         string `json:"message,omitempty"`
}

type AccessStatus struct {
	Account    AccountStatus    `json:"account"`
	Runtime    RuntimeStatus    `json:"runtime"`
	Datacenter DatacenterStatus `json:"datacenter"`
	Login      LoginStatus      `json:"login"`
	CheckedAt  string           `json:"checkedAt"`
}

type codexControl interface {
	Status(context.Context) AccessStatus
	StartLogin(context.Context) (LoginStatus, error)
}

type codexManager struct {
	pythonBin    string
	helperScript string
	mu           sync.Mutex
	login        LoginStatus
}

type loginFrame struct {
	Event           string `json:"event"`
	Success         bool   `json:"success"`
	VerificationURL string `json:"verificationUrl"`
	UserCode        string `json:"userCode"`
}

func newCodexManager(pythonBin, helperScript string) *codexManager {
	return &codexManager{
		pythonBin:    pythonBin,
		helperScript: helperScript,
		login:        LoginStatus{State: "idle"},
	}
}

func (m *codexManager) Status(ctx context.Context) AccessStatus {
	login := m.loginSnapshot()
	if login.State == "pending" {
		return AccessStatus{
			Account:    AccountStatus{State: "checking"},
			Runtime:    RuntimeStatus{State: "ready"},
			Datacenter: DatacenterStatus{State: "unavailable"},
			Login:      login,
			CheckedAt:  time.Now().UTC().Format(time.RFC3339),
		}
	}

	probeCtx, cancel := context.WithTimeout(ctx, statusTimeout)
	defer cancel()
	command := exec.CommandContext(probeCtx, m.pythonBin, m.helperScript, "status")
	output, err := command.Output()
	var status AccessStatus
	if err != nil || len(output) > maxFrameBytes || json.Unmarshal(bytes.TrimSpace(output), &status) != nil {
		status = unavailableStatus("status_probe_failed")
	}
	status.Login = login
	status.CheckedAt = time.Now().UTC().Format(time.RFC3339)
	return status
}

func (m *codexManager) StartLogin(ctx context.Context) (LoginStatus, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.login.State == "pending" {
		return m.login, nil
	}

	loginCtx, cancel := context.WithTimeout(context.Background(), loginTimeout)
	command := exec.CommandContext(loginCtx, m.pythonBin, m.helperScript, "login")
	output, err := command.StdoutPipe()
	if err != nil {
		cancel()
		return LoginStatus{}, err
	}
	var stderr bytes.Buffer
	command.Stderr = &stderr
	if err := command.Start(); err != nil {
		cancel()
		return LoginStatus{}, err
	}
	reader := bufio.NewReader(io.LimitReader(output, maxFrameBytes*2))
	type firstResult struct {
		frame loginFrame
		err   error
	}
	first := make(chan firstResult, 1)
	go func() {
		frame, readErr := readLoginFrame(reader)
		first <- firstResult{frame: frame, err: readErr}
	}()

	var result firstResult
	select {
	case result = <-first:
	case <-ctx.Done():
		cancel()
		_ = command.Wait()
		return LoginStatus{}, ctx.Err()
	case <-time.After(statusTimeout):
		cancel()
		_ = command.Wait()
		return LoginStatus{}, errors.New("Codex login start timed out")
	}
	if result.err != nil || result.frame.Event != "login-started" {
		cancel()
		_ = command.Wait()
		return LoginStatus{}, errors.New("Codex login did not start")
	}

	m.login = LoginStatus{
		State:           "pending",
		VerificationURL: result.frame.VerificationURL,
		UserCode:        result.frame.UserCode,
		Message:         "Conclua o acesso na página do Codex.",
	}
	go m.finishLogin(command, cancel, reader)
	return m.login, nil
}

func (m *codexManager) finishLogin(command *exec.Cmd, cancel context.CancelFunc, reader *bufio.Reader) {
	defer cancel()
	frame, readErr := readLoginFrame(reader)
	waitErr := command.Wait()
	m.mu.Lock()
	defer m.mu.Unlock()
	if readErr == nil && frame.Event == "login-completed" && frame.Success && waitErr == nil {
		m.login = LoginStatus{State: "completed", Message: "Conta Codex conectada."}
		return
	}
	m.login = LoginStatus{State: "failed", Message: "O acesso ao Codex não foi concluído. Tente novamente."}
}

func (m *codexManager) loginSnapshot() LoginStatus {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.login
}

func readLoginFrame(reader *bufio.Reader) (loginFrame, error) {
	line, err := reader.ReadString('\n')
	if err != nil {
		return loginFrame{}, err
	}
	if len(line) > maxFrameBytes {
		return loginFrame{}, fmt.Errorf("Codex login frame exceeds %d bytes", maxFrameBytes)
	}
	var frame loginFrame
	if err := json.Unmarshal([]byte(line), &frame); err != nil {
		return loginFrame{}, err
	}
	return frame, nil
}

func unavailableStatus(errorClass string) AccessStatus {
	return AccessStatus{
		Account:    AccountStatus{State: "unknown"},
		Runtime:    RuntimeStatus{State: "unavailable", ErrorClass: errorClass},
		Datacenter: DatacenterStatus{State: "unavailable"},
		Login:      LoginStatus{State: "idle"},
	}
}
