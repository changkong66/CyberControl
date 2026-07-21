<script setup lang="ts">
import { onMounted, ref, watch } from "vue"
import { computed } from "vue"
import { useI18n } from "vue-i18n"

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    message: string
    confirmLabel?: string
    cancelLabel?: string
  }>(),
  { confirmLabel: undefined, cancelLabel: undefined },
)
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const { t } = useI18n()
const resolvedConfirmLabel = computed(() => props.confirmLabel ?? t("common.confirm"))
const resolvedCancelLabel = computed(() => props.cancelLabel ?? t("common.cancel"))

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
      <button class="secondary-button" type="button" @click="cancel">{{ resolvedCancelLabel }}</button>
      <button class="primary-button" type="button" @click="$emit('confirm')">{{ resolvedConfirmLabel }}</button>
    </div>
  </dialog>
</template>
