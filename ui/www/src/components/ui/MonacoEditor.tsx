import Editor from '@monaco-editor/react'

interface MonacoEditorProps {
  value: string
  filename?: string
  language?: string
  readOnly?: boolean
  theme?: 'vs' | 'vs-dark' | 'hc-black'
  lineNumbers?: 'on' | 'off' | 'relative'
  wordWrap?: 'on' | 'off'
  minimap?: boolean
  scrollBeyondLastLine?: boolean
  automaticLayout?: boolean
  className?: string
}

const extensionToLanguage: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  vue: 'html',
  py: 'python',
  java: 'java',
  go: 'go',
  rs: 'rust',
  php: 'php',
  rb: 'ruby',
  c: 'c',
  cpp: 'cpp',
  h: 'c',
  hpp: 'cpp',
  md: 'markdown',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  sh: 'shell',
  bash: 'shell',
  html: 'html',
  css: 'css',
  scss: 'scss',
  sql: 'sql',
  toml: 'ini',
  ini: 'ini',
  xml: 'xml',
  dockerfile: 'dockerfile',
}

export default function MonacoEditor({
  value,
  filename,
  language,
  readOnly = false,
  theme = 'vs',
  lineNumbers = 'off',
  wordWrap = 'on',
  minimap = false,
  scrollBeyondLastLine = false,
  automaticLayout = true,
  className,
}: MonacoEditorProps) {
  const ext = filename?.split('.').pop()?.toLowerCase() ?? ''
  const lang = language ?? extensionToLanguage[ext] ?? 'plaintext'

  return (
    <Editor
      className={className}
      value={value}
      language={lang}
      theme={theme}
      options={{
        readOnly,
        lineNumbers,
        wordWrap,
        minimap: { enabled: minimap },
        scrollBeyondLastLine,
        automaticLayout,
        renderLineHighlight: 'none',
        contextmenu: false,
        scrollbar: { vertical: 'auto', horizontal: 'auto' },
      }}
    />
  )
}
