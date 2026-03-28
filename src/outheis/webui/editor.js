/**
 * outheis WebUI — CodeMirror 6 live-preview markdown editor
 *
 * Exposes window.MarkdownEditor.create(container, content, options) → editor handle.
 * Loaded as <script type="module"> so it can use ES module imports from esm.sh.
 */

import {
  EditorView, ViewPlugin, Decoration, WidgetType, keymap,
} from 'https://esm.sh/@codemirror/view@6'
import { EditorState, RangeSetBuilder } from 'https://esm.sh/@codemirror/state@6'
import { markdown } from 'https://esm.sh/@codemirror/lang-markdown@6'
import { GFM } from 'https://esm.sh/@lezer/markdown@1'
import {
  syntaxTree, HighlightStyle, syntaxHighlighting,
} from 'https://esm.sh/@codemirror/language@6'
import { defaultKeymap, history, historyKeymap } from 'https://esm.sh/@codemirror/commands@6'
import { tags } from 'https://esm.sh/@lezer/highlight@1'

// ── Highlight style ───────────────────────────────────────────────────────────
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
  '.cm-h1-line': { fontSize: '1.55em', fontWeight: '700', lineHeight: '1.4' },
  '.cm-h2-line': { fontSize: '1.25em', fontWeight: '600', lineHeight: '1.4' },
  '.cm-h3-line': { fontSize: '1.1em',  fontWeight: '600', lineHeight: '1.4' },
  '.cm-hr-line': { borderTop: '1px solid var(--border-primary)', color: 'transparent', userSelect: 'none' },
  '.cm-task-checkbox': { margin: '0 5px 0 0', cursor: 'pointer', verticalAlign: 'middle', width: '13px', height: '13px' },
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

// ── Checkbox widget ───────────────────────────────────────────────────────────
// Replaces "- [ ] " / "- [x] " with a real interactive checkbox.
// markerFrom: document position of the "[" character in "[ ]" / "[x]".
class CheckboxWidget extends WidgetType {
  constructor(checked, markerFrom) {
    super()
    this.checked = checked
    this.markerFrom = markerFrom
  }
  eq(other) { return this.checked === other.checked && this.markerFrom === other.markerFrom }
  toDOM(view) {
    const cb = document.createElement('input')
    cb.type = 'checkbox'
    cb.checked = this.checked
    cb.className = 'cm-task-checkbox'
    const mf = this.markerFrom
    const wasChecked = this.checked
    cb.addEventListener('mousedown', (e) => {
      e.preventDefault()
      view.dispatch({ changes: { from: mf + 1, to: mf + 2, insert: wasChecked ? ' ' : 'x' } })
    })
    return cb
  }
  ignoreEvent(e) { return e.type === 'mousedown' }
}

// ── Plugin A: Decoration.line for heading / HR lines ─────────────────────────
function buildLineDecos(view) {
  const { state } = view
  const cursorLines = getCursorLines(state)
  const builder = new RangeSetBuilder()

  syntaxTree(state).iterate({
    enter(node) {
      const lineNum = state.doc.lineAt(node.from).number
      if (node.name === 'ATXHeading1' || node.name === 'ATXHeading2' || node.name === 'ATXHeading3') {
        if (!cursorLines.has(lineNum)) {
          const lineFrom = state.doc.lineAt(node.from).from
          builder.add(lineFrom, lineFrom, Decoration.line({ class: `cm-h${node.name.slice(-1)}-line` }))
        }
        return false
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

// ── Plugin B: hide syntax markers + render task checkboxes ────────────────────
function buildHideDecos(view) {
  const { state } = view
  const cursorLines = getCursorLines(state)
  const ranges = []

  // Track the most recently seen ListMark so the TaskMarker handler can replace
  // "- [ ] " as a unit (list bullet + task marker + trailing space).
  let lastListMarkFrom = -1
  let lastListMarkLine = -1

  syntaxTree(state).iterate({
    enter(node) {
      const lineNum = state.doc.lineAt(node.from).number

      if (node.name === 'ListMark') {
        lastListMarkFrom = node.from
        lastListMarkLine = lineNum
        return
      }

      if (cursorLines.has(lineNum)) return

      if (node.name === 'HeaderMark') {
        let to = node.to
        if (to < state.doc.length && state.sliceDoc(to, to + 1) === ' ') to++
        ranges.push([node.from, to, null])
      } else if (node.name === 'EmphasisMark') {
        ranges.push([node.from, node.to, null])
      } else if (node.name === 'TaskMarker') {
        const checked = /[xX]/.test(state.sliceDoc(node.from + 1, node.from + 2))
        // Replace from the list bullet ("- ") through "[ ] " as one widget
        const from = (lastListMarkLine === lineNum && lastListMarkFrom >= 0)
          ? lastListMarkFrom
          : node.from
        let to = node.to
        if (to < state.doc.length && state.sliceDoc(to, to + 1) === ' ') to++
        ranges.push([from, to, new CheckboxWidget(checked, node.from)])
      }
    },
  })

  ranges.sort((a, b) => a[0] - b[0])

  const builder = new RangeSetBuilder()
  for (const [from, to, widget] of ranges) {
    builder.add(from, to, widget
      ? Decoration.replace({ widget })
      : Decoration.replace({}))
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
      markdown({ extensions: [GFM] }),
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
