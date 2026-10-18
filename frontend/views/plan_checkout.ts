import "@/css/plan_card.css";
import "@/css/browse_plans.css";
import "@/css/plan_checkout.css";

const Stripe = window["Stripe"] as any;

const STRIPE_STYLE = {
  base: {
    color: "#3F3F3F",
    fontSize: "18px",
    fontFamily: "system-ui, sans-serif",
    fontSmoothing: "antialiased",
    "::placeholder": {
      color: "#899194",
    },
  },
  invalid: {
    color: "#e5424d",
    ":focus": {
      color: "#303238",
    },
  },
};

type AjaxResult = { status: number; data: any };

function postForm(form: HTMLFormElement): Promise<AjaxResult> {
  return fetch(form.action || window.location.href, {
    method: "POST",
    headers: { "X-Requested-With": "XMLHttpRequest" },
    body: new FormData(form),
  }).then((response) =>
    response.json().then((data) => ({ status: response.status, data })),
  );
}

const NETWORK_ERROR = "A network error occurred. Please try again.";
const GENERIC_ERROR = "An error occurred. Please try again.";

const stripePk = (
  document.getElementById("id_stripe_pk") as HTMLInputElement | null
)?.value;
const stripe = stripePk && Stripe ? Stripe(stripePk) : null;

function initCardForm() {
  const form = document.getElementById("card-form") as HTMLFormElement | null;
  if (!form || !stripe) return;
  const toggle = document.getElementById("card-form-toggle");
  const cancel = document.getElementById("card-form-cancel");
  const tokenInput = document.getElementById(
    "id_stripe_token",
  ) as HTMLInputElement;
  const errors = document.getElementById("card-errors");

  const card = stripe.elements().create("card", { style: STRIPE_STYLE });
  card.mount("#card-element");
  card.on("change", (event: { error?: { message: string } }) => {
    errors.textContent = event.error?.message ?? "";
  });

  // We don't want the browser to fill this in with old values
  tokenInput.value = "";

  const setOpen = (open: boolean) => {
    form.hidden = !open;
    toggle?.setAttribute("aria-expanded", String(open));
    if (open) card.focus();
  };
  toggle?.addEventListener("click", () => setOpen(form.hidden as boolean));
  cancel?.addEventListener("click", () => {
    card.clear();
    errors.textContent = "";
    setOpen(false);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    stripe.createToken(card).then((result: any) => {
      if (result.error) {
        errors.textContent = result.error.message;
        return;
      }
      tokenInput.value = result.token.id;
      postForm(form)
        .then(({ status, data }) => {
          if (status >= 200 && status < 300) {
            // Reload rather than follow the redirect, to stay on checkout.
            window.location.reload();
          } else {
            errors.textContent = data.error || GENERIC_ERROR;
          }
        })
        .catch(() => {
          errors.textContent = NETWORK_ERROR;
        });
    });
  });
}

function initSubscribeForm() {
  const form = document.getElementById(
    "subscribe-form",
  ) as HTMLFormElement | null;
  if (!form) return;
  const button = document.getElementById(
    "subscribe-button",
  ) as HTMLButtonElement;
  const errors = document.getElementById("subscribe-errors");

  const fail = (message: string) => {
    errors.textContent = message;
    button.disabled = false;
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    button.disabled = true;
    errors.textContent = "";
    postForm(form)
      .then(({ status, data }) => {
        if (status === 402 && stripe) {
          stripe.confirmCardPayment(data.client_secret).then((result: any) => {
            if (result.error) {
              fail(result.error.message);
            } else {
              window.location.href = data.redirect;
            }
          });
        } else if (status >= 200 && status < 300) {
          window.location.href = data.redirect;
        } else {
          fail(data.error || GENERIC_ERROR);
        }
      })
      .catch(() => fail(NETWORK_ERROR));
  });
}

function initOrganizationSelect() {
  const select = document.getElementById(
    "organization-select",
  ) as HTMLSelectElement | null;
  select?.addEventListener("change", () => {
    window.location.href = select.value;
  });
}

initCardForm();
initSubscribeForm();
initOrganizationSelect();
