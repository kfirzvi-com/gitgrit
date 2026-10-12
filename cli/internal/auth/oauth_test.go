package auth

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

// fakeServer is a minimal authorization server: it "approves" every request
// by redirecting straight back with a code, and checks PKCE at the token
// endpoint.
type fakeServer struct {
	*httptest.Server
	challenge, redirect string
	deny                bool
	badIssuer           bool
}

func newFakeServer(t *testing.T) *fakeServer {
	f := &fakeServer{}
	mux := http.NewServeMux()
	mux.HandleFunc("/.well-known/oauth-authorization-server", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(Metadata{
			Issuer:                f.URL,
			AuthorizationEndpoint: f.URL + "/oauth/authorize/",
			TokenEndpoint:         f.URL + "/oauth/token/",
			RevocationEndpoint:    f.URL + "/oauth/revoke_token/",
		})
	})
	mux.HandleFunc("/oauth/authorize/", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		if q.Get("client_id") != ClientID || q.Get("code_challenge_method") != "S256" || q.Get("scope") != Scopes {
			t.Errorf("bad authorize request: %v", q)
		}
		f.challenge, f.redirect = q.Get("code_challenge"), q.Get("redirect_uri")
		back := url.Values{"state": {q.Get("state")}, "iss": {f.URL}}
		if f.badIssuer {
			back.Set("iss", "https://evil.example")
		}
		if f.deny {
			back.Set("error", "access_denied")
		} else {
			back.Set("code", "the-code")
		}
		http.Redirect(w, r, f.redirect+"?"+back.Encode(), http.StatusFound)
	})
	mux.HandleFunc("/oauth/token/", func(w http.ResponseWriter, r *http.Request) {
		r.ParseForm()
		sum := sha256.Sum256([]byte(r.Form.Get("code_verifier")))
		switch {
		case r.Form.Get("grant_type") == "refresh_token" && r.Form.Get("refresh_token") == "r1":
			json.NewEncoder(w).Encode(Token{AccessToken: "a2", RefreshToken: "r2", ExpiresIn: 3600})
		case r.Form.Get("code") == "the-code" &&
			base64.RawURLEncoding.EncodeToString(sum[:]) == f.challenge &&
			r.Form.Get("redirect_uri") == f.redirect:
			json.NewEncoder(w).Encode(Token{AccessToken: "a1", RefreshToken: "r1", ExpiresIn: 3600, Scope: Scopes})
		default:
			w.WriteHeader(http.StatusBadRequest)
			w.Write([]byte(`{"error":"invalid_grant","error_description":"nope"}`))
		}
	})
	f.Server = httptest.NewServer(mux)
	t.Cleanup(f.Close)
	return f
}

// browser follows the authorization URL the way a real browser would.
func browser(u string) error {
	go func() {
		resp, err := http.Get(u)
		if err == nil {
			resp.Body.Close()
		}
	}()
	return nil
}

func login(t *testing.T, f *fakeServer) (*Token, error) {
	md, err := Discover(context.Background(), http.DefaultClient, f.URL)
	if err != nil {
		t.Fatal(err)
	}
	return Login(context.Background(), http.DefaultClient, md, LoginOptions{OpenBrowser: browser, Timeout: 5 * time.Second})
}

func TestLoginRoundTrip(t *testing.T) {
	f := newFakeServer(t)
	tok, err := login(t, f)
	if err != nil {
		t.Fatal(err)
	}
	if tok.AccessToken != "a1" || tok.RefreshToken != "r1" {
		t.Errorf("token = %+v", tok)
	}
	if !strings.HasPrefix(f.redirect, "http://127.0.0.1:") || !strings.HasSuffix(f.redirect, "/callback") {
		t.Errorf("redirect_uri = %q; want a loopback callback", f.redirect)
	}
	if until := time.Until(tok.Expiry()); until < 59*time.Minute || until > time.Hour {
		t.Errorf("expiry in %v; want ~1h", until)
	}
}

func TestLoginDenied(t *testing.T) {
	f := newFakeServer(t)
	f.deny = true
	if _, err := login(t, f); err == nil || !strings.Contains(err.Error(), "access_denied") {
		t.Fatalf("err = %v; want access_denied", err)
	}
}

func TestLoginRejectsAnotherIssuer(t *testing.T) {
	f := newFakeServer(t)
	f.badIssuer = true
	if _, err := login(t, f); err == nil || !strings.Contains(err.Error(), "issuer mismatch") {
		t.Fatalf("err = %v; want issuer mismatch", err)
	}
}

func TestCallbackStateMustMatch(t *testing.T) {
	res := readCallback(url.Values{"state": {"other"}, "code": {"c"}}, "mine", "")
	if res.err == nil {
		t.Fatal("accepted a callback with the wrong state")
	}
}

func TestRefreshAndTokenErrors(t *testing.T) {
	f := newFakeServer(t)
	md, _ := Discover(context.Background(), http.DefaultClient, f.URL)
	tok, err := Refresh(context.Background(), http.DefaultClient, md, "r1")
	if err != nil || tok.AccessToken != "a2" || tok.RefreshToken != "r2" {
		t.Fatalf("Refresh = %+v, %v", tok, err)
	}
	_, err = Refresh(context.Background(), http.DefaultClient, md, "stale")
	var te *TokenError
	if err == nil || !errorsAs(err, &te) || te.Code != "invalid_grant" {
		t.Fatalf("err = %v; want invalid_grant TokenError", err)
	}
}

func TestPKCE(t *testing.T) {
	v, c := NewPKCE()
	if len(v) < 43 || len(v) > 128 {
		t.Errorf("verifier length %d outside 43..128", len(v))
	}
	sum := sha256.Sum256([]byte(v))
	if c != base64.RawURLEncoding.EncodeToString(sum[:]) {
		t.Error("challenge is not S256(verifier)")
	}
}

func errorsAs(err error, target **TokenError) bool {
	te, ok := err.(*TokenError)
	if ok {
		*target = te
	}
	return ok
}
