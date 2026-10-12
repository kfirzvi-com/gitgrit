// Command gitgrit is the GitGrit CLI.
package main

import (
	"os"

	"github.com/kfirzvi-com/gitgrit/cli/cmd"
)

func main() { os.Exit(cmd.Execute()) }
