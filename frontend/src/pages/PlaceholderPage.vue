<script setup lang="ts">
import { Inbox } from "@lucide/vue"

defineProps<{ title: string; status: string }>()
</script>

<template>
  <section class="page-section">
    <header class="page-heading">
      <h1>{{ title }}</h1>
    </header>
    <div class="empty-state">
      <Inbox :size="28" aria-hidden="true" />
      <span>{{ status }}</span>
    </div>
  </section>
</template>
