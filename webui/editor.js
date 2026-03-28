/**
 * outheis WebUI — CodeMirror 6 live-preview markdown editor
 *
 * Exposes window.MarkdownEditor.create(container, content, options) → editor handle.
 * Loaded as <script type="module"> so it can use ES module imports from esm.sh.
 */

import {
  EditorView, ViewPlugin, Decoration, keymap,
} from 'https://esm.sh/@codemirror/view@6'
import { EditorState, RangeSetBuilder } from 'https://esm.sh/@codemirror/state@6'
import { markdown } from 'https://esm.sh/@codemirror/lang-markdown@6'
import {
  syntaxTree, HighlightStyle, syntaxHighlighting,
} from 'https://esm.sh/@codemirror/language@6'
import { defaultKeymap, history, historyKeymap } from 'https://esm.sh/@codemirror/commands@6'
import { tags } from 'https://esm.sh/@lezer/highlight@1'

// ── Highlight style ───────────────────────────────────────────────────────────
// processingInstruction covers HeaderMark (##) and EmphasisMark (**) — shown
// in a dim colour on the cursor line, hidden by the plugin on other lines.
const mdHighlight = HighlightStyle.define([
  { tag: tags.processingInstruction, color: 'var(--text-tertiary)', opacity: '0.7' },
  { tag: tags.strong, fontWeight: '700' },
  { tag: tags.emphasis, fontStyle: 'italic' },
  { tag: tags.strikethrough, textDecoration: 'line-through' },
  { tag: tags.url, color: 'var(--accent-info)' },
  { tag: tags.link, color: 'var(--text-primary)' },
  { tag: tags.monospace, fontFamily: 'ui-monospace, monospace', fontSize: '0.88em' },
  { tag: tags.comment, color: 'var(--text-tertiary)', fontStyle: 'italic' },
])

// ── Theme ─────────────────────────────────────────────────────────────────────
const mdTheme = EditorView.theme({
  '&': { height: '100%' },
  '.cm-scroller': { overflow: 'auto', lineHeight: '1.75', fontFamily: 'inherit', fontSize: '13px' },
  '.cm-content': { padding: '24px 28px', maxWidth: '800px', caretColor: 'var(--text-primary)' },
  '.cm-line': { padding: '0' },
  '&.cm-focused': { outline: 'none' },
  '&.cm-focused .cm-cursor': { borderLeftColor: 'var(--text-primary)', borderLeftWidth: '1.5px' },
  '.cm-selectionBackground': { background: 'rgba(37,99,235,0.15) !important' },
  '&.cm-focused .cm-selectionBackground': { background: 'rgba(37,99,235,0.2) !important' },
  // Heading line classes — applied by lineStylePlugin to the whole line element
  '.cm-h1-line': { fontSize: '1.55em', fontWeight: '700', lineHeight: '1.4' },
  '.cm-h2-line': { fontSize: '1.25em', fontWeight: '600', lineHeight: '1.4' },
  '.cm-h3-line': { fontSize: '1.1em',  fontWeight: '600', lineHeight: '1.4' },
  // HR: hide the text, show a border
  '.cm-hr-line': {
    borderTop: '1px solid var(--border-primary)',
    color: 'transparent',
    userSelect: 'none',
  },
})

// ── Shared helper ─────────────────────────────────────────────────────────────
function getCursorLines(state) {
  const lines = new Set()
  for (const range of state.selection.ranges) {
    const a = state.doc.lineAt(range.from).number
    const b = state.doc.lineAt(range.to).number
    for (let i = a; i <= b; i++) lines.add(i)
  }
  return lines
}

// ── Plugin A: Decoration.line for heading / HR lines ─────────────────────────
// Uses zero-width line decorations — one per heading line, no overlaps possible.
function buildLineDecos(view) {
  const { state } = view
  const cursorLines = getCursorLines(state)
  const builder = new RangeSetBuilder()

  syntaxTree(state).iterate({
    enter(node) {
      const lineNum = state.doc.lineAt(node.from).number

      if (
        node.name === 'ATXHeading1' ||
        node.name === 'ATXHeading2' ||
        node.name === 'ATXHeading3'
      ) {
        if (!cursorLines.has(lineNum)) {
          const level = node.name.slice(-1)
          const lineFrom = state.doc.lineAt(node.from).from
          builder.add(lineFrom, lineFrom, Decoration.line({ class: `cm-h${level}-line` }))
        }
        return false // children (HeaderMark) handled by Plugin B
      }

      if (node.name === 'HorizontalRule') {
        if (!cursorLines.has(lineNum)) {
          const lineFrom = state.doc.lineAt(node.from).from
          builder.add(lineFrom, lineFrom, Decoration.line({ class: 'cm-hr-line' }))
        }
        return false
      }
    },
  })

  return builder.finish()
}

const lineStylePlugin = ViewPlugin.fromClass(
  class {
    constructor(view) { this.decorations = buildLineDecos(view) }
    update(update) {
      if (update.docChanged || update.selectionSet || update.viewportChanged)
        this.decorations = buildLineDecos(update.view)
    }
  },
  { decorations: (v) => v.decorations },
)

// ── Plugin B: Decoration.replace to hide syntax markers ───────────────────────
// Hides HeaderMark (## ) and EmphasisMark (** or *) on lines without the cursor.
// Collected into an array and sorted before building so the RangeSetBuilder
// receives strictly ascending from-positions.
function buildHideDecos(view) {
  const { state } = view
  const cursorLines = getCursorLines(state)
  const ranges = []

  syntaxTree(state).iterate({
    enter(node) {
      const lineNum = state.doc.lineAt(node.from).number
      if (cursorLines.has(lineNum)) return

      if (node.name === 'HeaderMark') {
        // Include the single trailing space that follows the #-sequence
        let to = node.to
        if (to < state.doc.length && state.sliceDoc(to, to + 1) === ' ') to++
        ranges.push([node.from, to])
      } else if (node.name === 'EmphasisMark') {
        ranges.push([node.from, node.to])
      }
    },
  })

  ranges.sort((a, b) => a[0] - b[0])

  const builder = new RangeSetBuilder()
  for (const [from, to] of ranges) {
    builder.add(from, to, Decoration.replace({}))
  }
  return builder.finish()
}

const syntaxHidePlugin = ViewPlugin.fromClass(
  class {
    constructor(view) { this.decorations = buildHideDecos(view) }
    update(update) {
      if (update.docChanged || update.selectionSet || update.viewportChanged)
        this.decorations = buildHideDecos(update.view)
    }
  },
  { decorations: (v) => v.decorations },
)

// ── Public factory ────────────────────────────────────────────────────────────
function createMarkdownEditor(container, initialContent, { onChange, onSave } = {}) {
  const saveBinding = onSave
    ? [{ key: 'Mod-s', run() { onSave(); return true } }]
    : []

  const state = EditorState.create({
    doc: initialContent,
    extensions: [
      history(),
      keymap.of([...saveBinding, ...historyKeymap, ...defaultKeymap]),
      EditorView.lineWrapping,
      markdown(),
      syntaxHighlighting(mdHighlight),
      lineStylePlugin,
      syntaxHidePlugin,
      mdTheme,
      EditorView.updateListener.of((update) => {
        if (update.docChanged && onChange) onChange(update.state.doc.toString())
      }),
    ],
  })

  const view = new EditorView({ state, parent: container })

  return {
    getContent() { return view.state.doc.toString() },
    setContent(text) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } })
    },
    focus() { view.focus() },
    destroy() { view.destroy() },
  }
}

window.MarkdownEditor = { create: createMarkdownEditor }
