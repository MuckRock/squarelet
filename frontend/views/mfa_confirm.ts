import "@/css/mfa_confirm.css";

// The backup codes must be downloaded before the user can continue.
document.addEventListener("DOMContentLoaded", () => {
  const downloadButton = document.getElementById("download-codes-btn");
  const continueButton = document.getElementById("continue-btn") as HTMLButtonElement | null;
  const continueHelpText = document.getElementById("continue-help");
  if (!downloadButton || !continueButton) return;

  downloadButton.addEventListener("click", () => {
    continueButton.disabled = false;
    if (continueHelpText) continueHelpText.style.display = "none";
  });
});
