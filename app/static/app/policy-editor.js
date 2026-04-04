import {
  EditorView, basicSetup,
  EditorState,
  python,
  autocompletion,
  oneDark,
  keymap,
  indentWithTab,
} from "./vendor/codemirror.bundle.js";

const PROJECT_METHODS = [
  {
    label: "list_files",
    type: "method",
    detail: "() -> list[str]",
    info: "List all files in the repository root.",
  },
  {
    label: "get_languages",
    type: "method",
    detail: "() -> dict[str, float]",
    info: "Language breakdown as {language: percentage}.",
  },
  {
    label: "get_members",
    type: "method",
    detail: "() -> list[dict]",
    info: "Project members. Each dict has keys: username, role.",
  },
  {
    label: "get_contributors",
    type: "method",
    detail: "() -> list[dict]",
    info: "Contributors. Each dict has keys: username, commits.",
  },
  {
    label: "get_default_branch",
    type: "method",
    detail: "() -> str",
    info: "Name of the default branch (e.g. 'main').",
  },
  {
    label: "get_topics",
    type: "method",
    detail: "() -> list[str]",
    info: "Repository topics/tags.",
  },
  {
    label: "get_metadata",
    type: "method",
    detail: "() -> dict",
    info: "Metadata: name, description, web_url, created_at, updated_at.",
  },
];

function projectCompletions(context) {
  const match = context.matchBefore(/project\.\w*/);
  if (!match || !match.text.includes(".")) return null;

  return {
    from: match.from + match.text.indexOf(".") + 1,
    options: PROJECT_METHODS,
    filter: true,
  };
}

const DEFAULT_CODE = `def evaluate(project):
    # Available methods:
    #   project.list_files()         -> list[str]
    #   project.get_languages()      -> dict[str, float]
    #   project.get_members()        -> list[dict]
    #   project.get_contributors()   -> list[dict]
    #   project.get_default_branch() -> str
    #   project.get_topics()         -> list[str]
    #   project.get_metadata()       -> dict
    #
    # Must return: {"passed": bool, "score": int, "message": str, "details": dict}

    return {
        "passed": True,
        "score": 100,
        "message": "Policy passed",
        "details": {},
    }
`;

export function initPolicyEditor(textareaId) {
  const textarea = document.getElementById(textareaId);
  if (!textarea) return;

  const initialCode = textarea.value.trim() || DEFAULT_CODE;
  textarea.style.display = "none";

  const updateListener = EditorView.updateListener.of((update) => {
    if (update.docChanged) {
      textarea.value = update.state.doc.toString();
    }
  });

  // Use Shadow DOM to isolate CodeMirror's injected <style> tags from
  // @tailwindcss/browser's MutationObserver, which otherwise fights
  // with CM and causes the editor to flash/disappear.
  const host = document.createElement("div");
  textarea.parentNode.insertBefore(host, textarea.nextSibling);
  const shadow = host.attachShadow({mode: "open"});

  const style = document.createElement("style");
  style.textContent = `
    .cm-editor { border: 1px solid rgba(255,255,255,0.15); border-radius: 0.5rem; }
    .cm-editor.cm-focused { outline: 2px solid oklch(0.65 0.24 265); outline-offset: 2px; }
  `;
  shadow.appendChild(style);

  const state = EditorState.create({
    doc: initialCode,
    extensions: [
      basicSetup,
      python(),
      oneDark,
      keymap.of([indentWithTab]),
      autocompletion({override: [projectCompletions]}),
      updateListener,
      EditorView.theme({
        "&": {fontSize: "14px"},
        ".cm-scroller": {fontFamily: "ui-monospace, monospace"},
      }),
    ],
  });

  new EditorView({state, parent: shadow, root: shadow});

  textarea.value = initialCode;
}
