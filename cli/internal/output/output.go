// Package output prints command results: tables for people, raw JSON
// (--json) for scripts and agents.
package output

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"text/tabwriter"
	"time"
)

// JSON pretty-prints an API response body as-is.
func JSON(w io.Writer, body []byte) error {
	var buf bytes.Buffer
	if err := json.Indent(&buf, body, "", "  "); err != nil {
		_, err = w.Write(body)
		return err
	}
	buf.WriteByte('\n')
	_, err := buf.WriteTo(w)
	return err
}

// Table writes aligned columns.
type Table struct{ tw *tabwriter.Writer }

// NewTable starts a table with a header row.
func NewTable(w io.Writer, header ...string) *Table {
	t := &Table{tw: tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)}
	t.Row(header...)
	return t
}

// Row adds a row.
func (t *Table) Row(cells ...string) { fmt.Fprintln(t.tw, strings.Join(cells, "\t")) }

// Flush writes the table out.
func (t *Table) Flush() { t.tw.Flush() }

// Ago is a short relative time: "5m ago", "3d ago".
func Ago(t time.Time) string {
	if t.IsZero() {
		return "—"
	}
	d := time.Since(t)
	switch {
	case d < time.Minute:
		return "just now"
	case d < time.Hour:
		return fmt.Sprintf("%dm ago", int(d.Minutes()))
	case d < 24*time.Hour:
		return fmt.Sprintf("%dh ago", int(d.Hours()))
	default:
		return fmt.Sprintf("%dd ago", int(d.Hours()/24))
	}
}

// Score renders an optional score.
func Score(s *int) string {
	if s == nil {
		return "—"
	}
	return fmt.Sprint(*s)
}

// Short is a 7-character commit SHA.
func Short(sha string) string {
	if len(sha) > 7 {
		return sha[:7]
	}
	if sha == "" {
		return "—"
	}
	return sha
}

// Status marks a check result.
func Status(s string) string {
	switch s {
	case "passed":
		return "✓ passed"
	case "failed":
		return "✗ failed"
	case "error":
		return "! error"
	case "running":
		return "… running"
	}
	return s
}
