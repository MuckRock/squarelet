import "@/css/mfa.css";

function copyRecoveryCodes() {
  const textarea = document.getElementById("recovery_codes") as HTMLTextAreaElement;
  if (!textarea) return;

  navigator.clipboard.writeText(textarea.value.trim());
  alert('Recovery codes have been copied to your clipboard. Please save them to a secure location.')
}

document.addEventListener("DOMContentLoaded", () => {
  const recoveryCodes = document.getElementById("recovery-codes");
  if (!recoveryCodes) return;

  const copyButton = recoveryCodes.querySelector("#copy-recovery-codes");
  if (copyButton) {
    copyButton.addEventListener("click", copyRecoveryCodes);
  }
});
