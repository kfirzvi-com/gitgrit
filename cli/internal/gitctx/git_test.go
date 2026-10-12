package gitctx

import "testing"

func TestFullPath(t *testing.T) {
	cases := map[string]string{
		"git@github.com:acme/api.git":                         "acme/api",
		"https://github.com/acme/api":                         "acme/api",
		"https://github.com/acme/api.git/":                    "acme/api",
		"ssh://git@gitlab.example.com:2222/group/sub/api.git": "group/sub/api",
		"https://oauth2:tok@gitlab.com/group/api.git":         "group/api",
		"":           "",
		"/local/dir": "",
	}
	for in, want := range cases {
		if got := FullPath(in); got != want {
			t.Errorf("FullPath(%q) = %q; want %q", in, got, want)
		}
	}
}

func TestSafeRemote(t *testing.T) {
	cases := map[string]string{
		"https://oauth2:glpat-secret@gitlab.com/group/api.git": "https://gitlab.com/group/api.git",
		"https://x-access-token:ghs_x@github.com/acme/api":     "https://github.com/acme/api",
		"ssh://git:pw@gitlab.example.com/group/api.git":        "ssh://git@gitlab.example.com/group/api.git",
		"git@github.com:acme/api.git":                          "git@github.com:acme/api.git",
		"https://github.com/acme/api":                          "https://github.com/acme/api",
	}
	for in, want := range cases {
		if got := SafeRemote(in); got != want {
			t.Errorf("SafeRemote(%q) = %q; want %q", in, got, want)
		}
	}
}
