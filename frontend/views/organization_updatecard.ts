import { d, exists, on } from "../util";

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

export class UpdateCardView {
  readonly stripePkInput = d("id_stripe_pk") as HTMLInputElement;
  readonly tokenInput = d("id_stripe_token") as HTMLInputElement;
  readonly errorElem = d("card-errors");
  readonly form = d("stripe-form") as HTMLFormElement;

  constructor() {
    this.initUpdateCardForm();
  }

  initUpdateCardForm(): void {
    const stripePk = this.stripePkInput.value;
    if (!stripePk || !Stripe) return;

    const stripe = Stripe(stripePk);
    const elements = stripe.elements();
    const card = elements.create("card", { style: STRIPE_STYLE });
    card.mount("#card-element");

    card.addEventListener(
      "change",
      (event: { error?: { message: string } }) => {
        this.errorElem.textContent = event.error?.message ?? "";
      },
    );

    // We don't want the browser to fill this in with old values
    this.tokenInput.value = "";

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();

      // Create token for new card, then AJAX submit
      stripe.createToken(card).then((result) => {
        if (result.error) {
          this.errorElem.textContent = result.error.message;
        } else {
          (
            document.getElementById("id_stripe_token") as HTMLInputElement
          ).value = result.token.id;
          this.submitViaAjax();
        }
      });
    });
  }

  submitViaAjax() {
    fetch(this.form.action || window.location.href, {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body: new FormData(this.form),
    })
      .then((response) =>
        response.json().then((data) => ({ status: response.status, data })),
      )
      .then(({ status, data }) => {
        if (status >= 200 && status < 300) {
          window.location.href = data.redirect;
        } else {
          if (this.errorElem) {
            this.errorElem.textContent =
              data.error || "An error occurred. Please try again.";
          }
        }
      })
      .catch(() => {
        if (this.errorElem) {
          this.errorElem.textContent =
            "A network error occurred. Please try again.";
        }
      });
  }
}

/* Load the UpdateCardView */
if (exists("id_stripe_pk")) {
  new UpdateCardView();
}
