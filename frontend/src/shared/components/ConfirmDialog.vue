<script setup lang="ts">
import { onMounted, ref, watch } from "vue"

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    message: string
    confirmLabel?: string
  }>(),
  { confirmLabel: "确认" },
)
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)

function syncOpen(open: boolean): void {
  if (open && !dialog.value?.open) dialog.value?.showModal()
  if (!open && dialog.value?.open) dialog.value.close()
}

watch(
  () => props.open,
  syncOpen,
)
onMounted(() => syncOpen(props.open))

function cancel(): void {
  emit("cancel")
}
</script>

<template>
  <dialog ref="dialog" class="confirm-dialog" @cancel.prevent="cancel">
    <h2>{{ title }}</h2>
    <p>{{ message }}</p>
    <div class="dialog-actions">
      <button class="secondary-button" type="button" @click="cancel">取消</button>
      <button class="primary-button" type="button" @click="$emit('confirm')">{{ confirmLabel }}</button>
    </div>
  </dialog>
</template>
