import "@/css/subscribe.css";

const cardInputStyle = {
  base: {
    backgroundColor: "#FFFFFF",
    color: "#3F3F3F",
    fontSize: "16px",
    fontFamily: '"Source Sans 3", "Source Sans Pro", system-ui, sans-serif',
    fontSmoothing: "antialiased",
    "::placeholder": {
      color: "#899194",
    },
    padding: "0.25rem 0.5rem",
  },
  invalid: {
    color: "#e5424d",
    ":focus": {
      color: "#303238",
    },
  },
};

function initTabs() {
  const tabContainer = document.querySelector<HTMLElement>(".tab-group");
  const individualTab = document.querySelector<HTMLElement>(".tab.individual");
  const groupTab = document.querySelector<HTMLElement>(".tab.group");
  const individualContent = document.querySelector<HTMLElement>(".tab-content.individual");
  const groupContent = document.querySelector<HTMLElement>(".tab-content.group");
  if (!tabContainer || !individualTab || !groupTab || !individualContent || !groupContent) {
    return;
  }

  individualTab.addEventListener("click", () => {
    tabContainer.dataset.activeTab = "individual";
    individualTab.classList.add("active");
    groupTab.classList.remove("active");
    individualContent.style.display = "flex";
    groupContent.style.display = "none";
  });

  groupTab.addEventListener("click", () => {
    tabContainer.dataset.activeTab = "group";
    groupTab.classList.add("active");
    individualTab.classList.remove("active");
    groupContent.style.display = "flex";
    individualContent.style.display = "none";
  });

  if (tabContainer.dataset.selectedPlan === "organization") {
    groupTab.click();
  } else {
    individualTab.click();
  }
}

function initNewOrganizationField() {
  const form = document.getElementById("group-org");
  if (!form) return;

  // The individual form renders a field with the same id, so look inside this form.
  const byId = (id: string = "") => form.querySelector<HTMLElement>(`#${CSS.escape(id)}`);
  const select = byId(form.dataset.organizationField) as HTMLSelectElement | null;
  const field = byId(form.dataset.newOrganizationField);
  const label = field?.closest("label");
  if (!select || !field || !label) return;

  const toggle = () => {
    const display = select.value === "new" ? "block" : "none";
    label.style.display = display;
    field.style.display = display;
  };

  toggle();
  select.addEventListener("change", toggle);
}

function initCardField(cardField: HTMLElement) {
  const form = cardField.closest("form");
  if (!form) return;

  const stripePk = form.querySelector<HTMLInputElement>("#id_stripe_pk")!.value;
  const tokenInput = form.querySelector<HTMLInputElement>("#id_stripe_token")!;
  const errorDisplay = cardField.querySelector<HTMLElement>(".card-element-errors");
  const showError = (message: string) => {
    if (errorDisplay) errorDisplay.textContent = message;
  };

  const stripe = Stripe(stripePk);
  const cardElement = stripe.elements().create("card", { style: cardInputStyle });
  cardElement.mount(cardField.querySelector(".card-element")!);

  cardElement.on("change", (event) => {
    showError(event?.error?.message ?? "");
  });

  // The browser must not refill this with an old token.
  tokenInput.value = "";

  // Submit by AJAX so a card needing 3DS can be confirmed before redirecting.
  async function submitViaAjax() {
    try {
      const response = await fetch(form!.action, {
        method: "POST",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        body: new FormData(form!),
      });
      const data = await response.json();

      if (response.status === 402) {
        const confirmation = await stripe.confirmCardPayment(data.client_secret);
        if (confirmation.error) {
          showError(confirmation.error.message ?? "");
        } else {
          window.location.href = data.redirect;
        }
      } else if (response.status >= 200 && response.status < 300) {
        window.location.href = data.redirect;
      } else {
        showError(data.error || "An error occurred. Please try again.");
      }
    } catch {
      showError("A network error occurred. Please try again.");
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (tokenInput.value) {
      submitViaAjax();
      return;
    }

    const result = await stripe.createToken(cardElement);
    if (result.error) {
      showError(result.error.message ?? "");
    } else {
      tokenInput.value = result.token!.id;
      submitViaAjax();
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initNewOrganizationField();
  // Last, so a Stripe.js that failed to load cannot take the tabs down with it.
  document.querySelectorAll<HTMLElement>(".card-field").forEach(initCardField);
});
