package manifest

import (
	"encoding/json"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

// Manifest represents a full machine state snapshot.
type Manifest struct {
	Hostname  string    `json:"hostname"`
	OS        string    `json:"os"`
	Arch      string    `json:"arch"`
	Generated time.Time `json:"generated"`
	Homebrew  Homebrew  `json:"homebrew"`
	Python    PkgList   `json:"python"`
	Node      PkgList   `json:"node"`
	Docker    Docker    `json:"docker"`
	VSCode    VSCode    `json:"vscode"`
	Shell     Shell     `json:"shell"`
	SSH       SSH       `json:"ssh"`
	Git       GitConfig `json:"git"`
}

type Homebrew struct {
	Formulae []string `json:"formulae"`
	Casks    []string `json:"casks"`
}

type PkgList struct {
	Version  string   `json:"version"`
	Packages []string `json:"packages"`
}

type Docker struct {
	Images []string `json:"images"`
}

type VSCode struct {
	Extensions []string `json:"extensions"`
}

type Shell struct {
	Default string `json:"default"`
}

type SSH struct {
	Keys        []string `json:"keys"`
	ConfigHosts []string `json:"config_hosts"`
}

type GitConfig struct {
	UserName string `json:"user_name"`
	UserEmail string `json:"user_email"`
}

// Collect gathers the full machine manifest.
func Collect() (*Manifest, error) {
	hostname, _ := os.Hostname()

	m := &Manifest{
		Hostname:  strings.ToLower(hostname),
		OS:        runtime.GOOS,
		Arch:      runtime.GOARCH,
		Generated: time.Now().UTC(),
	}

	m.Homebrew = collectHomebrew()
	m.Python = collectPython()
	m.Node = collectNode()
	m.Docker = collectDocker()
	m.VSCode = collectVSCode()
	m.Shell = collectShell()
	m.SSH = collectSSH()
	m.Git = collectGit()

	return m, nil
}

// ToJSON serializes the manifest to indented JSON.
func (m *Manifest) ToJSON() ([]byte, error) {
	return json.MarshalIndent(m, "", "  ")
}

func runCmd(name string, args ...string) []string {
	out, err := exec.Command(name, args...).Output()
	if err != nil {
		return nil
	}
	lines := strings.Split(strings.TrimSpace(string(out)), "\n")
	var result []string
	for _, l := range lines {
		l = strings.TrimSpace(l)
		if l != "" {
			result = append(result, l)
		}
	}
	return result
}

func collectHomebrew() Homebrew {
	return Homebrew{
		Formulae: runCmd("brew", "list", "--formula", "-1"),
		Casks:    runCmd("brew", "list", "--cask", "-1"),
	}
}

func collectPython() PkgList {
	ver := runCmd("python3", "--version")
	version := ""
	if len(ver) > 0 {
		version = strings.TrimPrefix(ver[0], "Python ")
	}
	pkgs := runCmd("pip3", "list", "--format=freeze", "--user")
	var names []string
	for _, p := range pkgs {
		parts := strings.SplitN(p, "==", 2)
		if len(parts) > 0 {
			names = append(names, parts[0])
		}
	}
	return PkgList{Version: version, Packages: names}
}

func collectNode() PkgList {
	ver := runCmd("node", "--version")
	version := ""
	if len(ver) > 0 {
		version = strings.TrimPrefix(ver[0], "v")
	}
	raw := runCmd("npm", "list", "-g", "--depth=0", "--parseable")
	var names []string
	for _, p := range raw {
		base := p[strings.LastIndex(p, "/")+1:]
		if base != "" && base != "lib" {
			names = append(names, base)
		}
	}
	return PkgList{Version: version, Packages: names}
}

func collectDocker() Docker {
	images := runCmd("docker", "images", "--format", "{{.Repository}}:{{.Tag}}")
	return Docker{Images: images}
}

func collectVSCode() VSCode {
	exts := runCmd("code", "--list-extensions")
	return VSCode{Extensions: exts}
}

func collectShell() Shell {
	sh := os.Getenv("SHELL")
	if sh == "" {
		sh = "/bin/zsh"
	}
	return Shell{Default: sh}
}

func collectSSH() SSH {
	home, _ := os.UserHomeDir()
	sshDir := home + "/.ssh"

	var keys []string
	entries, err := os.ReadDir(sshDir)
	if err == nil {
		for _, e := range entries {
			if strings.HasPrefix(e.Name(), "id_") && strings.HasSuffix(e.Name(), ".pub") {
				keys = append(keys, strings.TrimSuffix(e.Name(), ".pub"))
			}
		}
	}

	var hosts []string
	configData, err := os.ReadFile(sshDir + "/config")
	if err == nil {
		for _, line := range strings.Split(string(configData), "\n") {
			line = strings.TrimSpace(line)
			if strings.HasPrefix(strings.ToLower(line), "host ") {
				host := strings.TrimSpace(line[5:])
				if host != "*" {
					hosts = append(hosts, host)
				}
			}
		}
	}

	return SSH{Keys: keys, ConfigHosts: hosts}
}

func collectGit() GitConfig {
	name := runCmd("git", "config", "--global", "user.name")
	email := runCmd("git", "config", "--global", "user.email")
	gc := GitConfig{}
	if len(name) > 0 {
		gc.UserName = name[0]
	}
	if len(email) > 0 {
		gc.UserEmail = email[0]
	}
	return gc
}
