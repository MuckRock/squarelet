import { d, exists, on } from "../util";
// import { StripeAPIError } from 'stripe/lib/Error';
// const Stripe = require('stripe') as StripeAPIError;
// TODO: get Stripe import to work.
const Stripe = window["Stripe"] as any;

// Helper function to format numbers with commas
function formatPrice(price: number): string {
  return price.toLocaleString('en-US');
}

/**
 * A Squarelet plan.
 */
interface Plan {
  pk: number;
  slug: string;
  base_price: number;
  price_per_user: number;
  minimum_users: number;
  annual: boolean;
}

// Style for the Stripe card element.
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

/**
 * Set up and handle reactive views related to paid plans.
 */
export class PlansView {
  readonly stripePk = d("id_stripe_pk") as HTMLInputElement; // hidden Stripe key
  readonly planInput = d("id_plan") as HTMLInputElement;
  readonly ucofInput = d("id_use_card_on_file") as HTMLInputElement;
  readonly rcofInput = d("id_remove_card_on_file") as HTMLInputElement;
  readonly ccFieldset = d("_id-cardFieldset");
  readonly removeCardFieldset = d("_id-removeCardFieldset");

  readonly planInfoElem = d("_id-planInfo"); // Pane to show plan information
  readonly planProjection = d("_id-planProjection"); // Plan projection information
  readonly cardContainer = d("card-container"); // Credit card container.

  readonly receiptEmails = d("_id-receiptEmails") as HTMLTextAreaElement;
  readonly totalCost = d("_id-totalCost");
  readonly costBreakdown = d("_id-costBreakdown");

  readonly maxUsersElem = d("id_max_users") as HTMLInputElement | null;

  readonly planInfo: { [key: number]: Plan } = JSON.parse(
    this.planInfoElem.textContent,
  );

  public maxUsers: number;

  constructor() {
    this.setupMaxUsersField();
    this.setupCardOnFileField();
    this.setupReceiptEmails();
    this.setupStripe();
    this.updateAll();
  }

  /**
   * Resize the receipt emails to match the text content.
   */
  receiptResize() {
    // Set a small initial height to derive the scroll height.
    this.receiptEmails.style.height = "5px";
    this.receiptEmails.style.height = this.receiptEmails.scrollHeight + "px";
  }

  /**
   * Returns the currently selected plan information.
   */
  getPlan(): Plan {
    return this.planInfo[this.planInput.value] || this.planInfo[""];
  }

  /**
   * Update the total cost breakdown text.
   * TODO: figure out i18n for these strings
   */
  updateTotalCost() {
    // Don't update total cost if the element isn't present
    if (this.totalCost == null) return;

    const plan = this.getPlan();
    const cost = plan.base_price + (this.maxUsers - plan.minimum_users) * plan.price_per_user;
    const timePeriod = plan.annual ? "year" : "month";
    const costFormatted = `$${formatPrice(cost)} / ${timePeriod}`;
    this.totalCost.textContent = costFormatted;

    let costBreakdownFormatted = `$${formatPrice(plan.base_price)} (base price)`;
    if (this.maxUsers != 0) {
      if (this.maxUsers - plan.minimum_users == 0) {
        costBreakdownFormatted += ` with ${plan.minimum_users} resource block${
          plan.minimum_users != 1 ? "s" : ""
        } included`;
        if (plan.price_per_user != 0) {
          costBreakdownFormatted += ` ($${formatPrice(plan.price_per_user)} per additional resouece block)`;
        }
      } else {
        costBreakdownFormatted += ` with ${plan.minimum_users} resource block${
          plan.minimum_users != 1 ? "s" : ""
        } included and ${this.maxUsers - plan.minimum_users} extra resource blocks
          at $${formatPrice(plan.price_per_user)} each`;
      }
    }
    this.costBreakdown.textContent = costBreakdownFormatted;
  }

  /**
   * Handle updates to the plan selection.
   */
  updatePlanInput() {
    const plan = this.getPlan();

    this.updateTotalCost();

    // TODO: use util function for this display logic.
    // show credit card field only if payment is required
    if (requiresPayment(plan)) {
      if (this.ccFieldset != null) {
        this.ccFieldset.style.display = "";
      }
      if (this.removeCardFieldset != null) {
        this.removeCardFieldset.style.display = "none";
      }
    } else {
      if (this.ccFieldset != null) {
        this.ccFieldset.style.display = "none";
      }
      if (this.removeCardFieldset != null) {
        this.removeCardFieldset.style.display = "";
      }
    }

    // show cost projection for any non-free plan,
    // including annually invoiced plans
    if (isFree(plan)) {
      if (this.planProjection != null) {
        this.planProjection.style.display = "none";
      }
    } else {
      if (this.planProjection != null) {
        this.planProjection.style.display = "";
      }
    }

    const maxUsers = document.querySelector("#id_max_users");
    if (maxUsers) {
      const fieldset = maxUsers.closest("fieldset");
      const hint = document.querySelector("#hint_id_max_users");
      if (plan.slug === "") {
        // The canonical free plan assigns no resources, so do not show the resource
        // blocks field
        fieldset.style.display = "none";
      } else if (plan.slug == "organization") {
        // The normal organization plan does show the resource block
        // Add specific help text for it as well
        fieldset.style.display = "";
        hint.textContent = `Your plan covers unlimited users.  By default, this organization plan
          includes 50 requests on MuckRock as well as 5,000 credits for
          DocumentCloud premium features, both renewed monthly on your billing
          date.  Each additional resource block above 5 will grant you another 10
          requests and 500 premium credits.`;
      } else {
        // Custom plans show the resource block field and have generic help
        fieldset.style.display = "";
        hint.textContent = `You have selected a custom plan.  Please contact a staff member for
          specific details on how many resources each resource block will
          provide.`;
      }
    }

    this.updateAll(false);
  }

  /**
   * Handle changes to the max users element.
   */
  updateMaxUsers() {
    if (this.maxUsersElem == null) return;
    this.maxUsers = parseInt(this.maxUsersElem.value);
    const minUsers = parseInt(this.maxUsersElem.min);
    if (this.maxUsers < minUsers) {
      this.maxUsersElem.value = `${minUsers}`;
      this.maxUsers = minUsers;
    }
  }

  /**
   * Handle changes to the saved credit card selection.
   */
  updateSavedCC() {
    if (this.ucofInput == null) {
      if (this.cardContainer != null) {
        this.cardContainer.style.display = "";
      }
      return;
    }
    const ucofInput = document.querySelector(
      "input[name=use_card_on_file]:checked",
    ) as HTMLInputElement;
    if (ucofInput.value == "True" && this.ccFieldset.style.display === "") {
      if (this.cardContainer != null) {
        // TODO: Use utility hide function
        this.cardContainer.style.display = "none";
      }
    } else {
      if (this.cardContainer != null) {
        this.cardContainer.style.display = "";
      }
    }
  }

  /**
   * Updates the max users, saved credit card, and plan input selections simultaneously.
   * This method is used to safely ensure changes are recognized by all reactive
   * components.
   * @param updatePlanInput Whether to also update the plan input. This is set to false
   * when the plan input calls this method to avoid infinite loops.
   */
  updateAll(updatePlanInput = true) {
    this.updateMaxUsers();
    this.updateSavedCC();
    if (updatePlanInput) this.updatePlanInput();
  }

  /**
   * Set up event listeners and variables related to the max users setting.
   */
  setupMaxUsersField() {
    if (exists("id_max_users")) {
      // Handle reactive max user updates if field is defined.
      const maxUsersElem = this.maxUsersElem as HTMLInputElement;
      this.maxUsers = parseInt(maxUsersElem.value);
      on(maxUsersElem, "blur", () => {
        this.updateAll();
      });
    } else {
      const plan = this.getPlan();
      this.maxUsers = plan.minimum_users;
    }
  }

  /**
   * Set up event listeners and variables related to the card on file field.
   */
  setupCardOnFileField() {
    if (exists("id_use_card_on_file")) {
      on(this.ucofInput, "input", () => {
        this.updateAll();
      });
    }
  }

  /**
   * Set up event listeners and variables related to the receipt emails field.
   */
  setupReceiptEmails() {
    if (this.receiptEmails == null) return;
    // Make receipt emails field auto-resize.
    this.receiptEmails.rows = 2;
    on(this.receiptEmails, "input", () => this.receiptResize());
    this.receiptResize();
  }

  /**
   * Set up event listeners and variables related to Stripe.
   */
  setupStripe() {
    if (exists("card-element")) {
      const stripe = Stripe(this.stripePk.value);
      const elements = stripe.elements();

      // Decorate card.
      const card = elements.create("card", { style: STRIPE_STYLE });
      card.mount("#card-element");
      (card as unknown as HTMLElement).addEventListener("change", (event) => {
        const changeEvent = event as { error?: { message: string } };
        // Show Stripe errors.
        const displayError = document.getElementById("card-errors");
        if (changeEvent.error) {
          displayError.textContent = changeEvent.error.message;
        } else {
          displayError.textContent = "";
        }
      });

      // We don't want the browser to fill this in with old values
      (document.getElementById("id_stripe_token") as HTMLInputElement).value =
        "";

      // only show payment fields if needed

      this.planInput.addEventListener("input", () => {
        this.updateAll();
      });

      // Create a token or display an error when the form is submitted.
      const form = document.getElementById("stripe-form") as HTMLFormElement;
      form.addEventListener("submit", (event) => {
        event.preventDefault();

        const ucofInput = document.querySelector(
          "input[name=use_card_on_file]:checked",
        ) as HTMLInputElement;
        const useCardOnFile = ucofInput != null && ucofInput.value == "True";
        const plan = this.getPlan();
        const ccEmpty = document
          .querySelector("#card-element")
          .classList.contains("StripeElement--empty");
        const errorElement = document.getElementById("card-errors");

        const submitAjax = () =>
          submitFormAjax(form, stripe, errorElement);

        if (useCardOnFile || (isFree(plan) && ccEmpty)) {
          // No new card — submit directly via AJAX
          submitAjax();
        } else {
          // Create token for new card, then AJAX submit
          stripe.createToken(card).then((result) => {
            if (result.error) {
              errorElement.textContent = result.error.message;
            } else {
              (
                document.getElementById("id_stripe_token") as HTMLInputElement
              ).value = result.token.id;
              submitAjax();
            }
          });
        }
      });
    }
  }
}

/**
 * Submit the form via AJAX, handling 402 Payment Action Required (3DS).
 * On 402: calls stripe.confirmCardPayment then redirects.
 * On success: redirects to the URL in the JSON response.
 * On error: displays the error message.
 */
function submitFormAjax(
  form: HTMLFormElement,
  stripe: any,
  errorElement: HTMLElement,
): void {
  fetch(form.action || window.location.href, {
    method: "POST",
    headers: { "X-Requested-With": "XMLHttpRequest" },
    body: new FormData(form),
  })
    .then((response) =>
      response.json().then((data) => ({ status: response.status, data })),
    )
    .then(({ status, data }) => {
      if (status === 402) {
        stripe
          .confirmCardPayment(data.client_secret)
          .then((result: { error?: { message: string } }) => {
            if (result.error) {
              errorElement.textContent = result.error.message;
            } else {
              window.location.href = data.redirect;
            }
          });
      } else if (status >= 200 && status < 300) {
        window.location.href = data.redirect;
      } else {
        errorElement.textContent =
          data.error || "An error occurred. Please try again.";
      }
    })
    .catch(() => {
      errorElement.textContent =
        "A network error occurred. Please try again.";
    });
}

/**
 * Return whether the specified plan is free.
 */
function isFree(plan: Plan): boolean {
  return plan.base_price == 0 && plan.price_per_user == 0;
}

/**
 * Return whether the specified plan requires payment
 * The plan requires payment if it is not free and not billed via invoice annually
 */
function requiresPayment(plan: Plan): boolean {
  return !isFree(plan) && !plan.annual;
}

/* Load the PlanView */
if (exists("id_stripe_pk")) {
  // Stripe and plans pages.
  new PlansView();
}
