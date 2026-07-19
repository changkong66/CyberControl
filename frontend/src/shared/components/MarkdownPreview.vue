<script setup lang="ts">
import { computed } from "vue"

const props = defineProps<{ source?: string | null }>()

function escapeHtml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;")
}

const rendered = computed(() => {
  const source = props.source?.trim() ?? ""
  if (!source) return "<p class=\"markdown-muted\">暂无可展示内容。</p>"
  const lines = source.split(/\r?\n/u)
  let inCode = false
  const output: string[] = []
  for (const line of lines) {
    if (line.startsWith("```")) {
      if (inCode) output.push("</code></pre>")
      else output.push("<pre><code>")
      inCode = !inCode
      continue
    }
    if (inCode) {
      output.push(escapeHtml(line) + "\n")
      continue
    }
    if (line.startsWith("### ")) output.push(`<h4>${escapeHtml(line.slice(4))}</h4>`)
    else if (line.startsWith("## ")) output.push(`<h3>${escapeHtml(line.slice(3))}</h3>`)
    else if (line.startsWith("# ")) output.push(`<h2>${escapeHtml(line.slice(2))}</h2>`)
    else if (line.startsWith("- ")) output.push(`<li>${escapeHtml(line.slice(2))}</li>`)
    else if (line.trim()) output.push(`<p>${escapeHtml(line)}</p>`)
  }
  if (inCode) output.push("</code></pre>")
  return output.join("")
})
</script>

<template>
  <div class="markdown-preview" v-html="rendered" />
</template>
