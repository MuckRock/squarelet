import "./css/avatar_widget.css";

// Enhances every widgets/avatar.html on the page: previews the chosen file
// and keeps the clear checkbox and button in step with it.
function initAvatarWidget(container: HTMLElement) {
  const fileInput = container.querySelector<HTMLInputElement>("[data-avatar-input]");
  const preview = container.querySelector<HTMLImageElement>("img[data-avatar-preview]");
  const clearCheckbox = container.querySelector<HTMLInputElement>("[data-avatar-clear-checkbox]");
  const clearButton = container.querySelector<HTMLButtonElement>("[data-avatar-clear-button]");
  if (!fileInput || !preview) return;

  const hadFile = container.dataset.hasFile === "true";
  const selectedAlt = container.dataset.selectedAlt ?? "";

  function setState(hasFile: boolean) {
    // Keep the checkbox enabled while checked so the form still submits the clear flag.
    if (clearCheckbox) clearCheckbox.disabled = !hasFile && !clearCheckbox.checked;
    if (clearButton) clearButton.disabled = !hasFile;
  }

  function showPreview(file: File) {
    preview!.alt = selectedAlt;
    preview!.src = URL.createObjectURL(file);
    preview!.parentElement?.classList.add("has-file");
  }

  function clearPreview() {
    preview!.parentElement?.classList.remove("has-file");
    preview!.src = "";
  }

  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    if (file) {
      showPreview(file);
      setState(true);
      if (clearCheckbox) clearCheckbox.checked = false;
    } else {
      clearPreview();
      setState(false);
    }
  });

  clearButton?.addEventListener("click", () => {
    if (clearButton.disabled) return;
    fileInput.value = "";
    clearPreview();
    if (clearCheckbox) {
      clearCheckbox.checked = true;
      clearCheckbox.disabled = false;
    }
    setState(false);
  });

  clearCheckbox?.addEventListener("change", () => {
    if (clearCheckbox.checked) {
      fileInput.value = "";
      if (clearButton) clearButton.disabled = true;
    } else if (hadFile && clearButton) {
      clearButton.disabled = false;
    }
  });

  setState(hadFile);
}

export function initAvatarWidgets() {
  document
    .querySelectorAll<HTMLElement>("[data-avatar-widget]")
    .forEach(initAvatarWidget);
}
