import {d, exists, on} from './util';

// TODO: get Stripe import to work.
const Stripe = window['Stripe'] as any;

// TODO: clean up this code significantly

/**
 * A Squarelet plan.
 */
interface Plan {
  pk: number;
  base_price: number;
  price_per_user: number;
  minimum_users: number;
}

/**
 * Return whether the specified plan is free.
 */
function isFree(plan: Plan): boolean {
  return plan.base_price == 0 && plan.price_per_user == 0 && plan.minimum_users == 1;
}

export class StripeView {
  readonly stripePk = d('id_stripe_pk') as HTMLInputElement;
  readonly planInput = d('id_plan') as HTMLInputElement;
  readonly planInfoElem = d('_id-planInfo');
  readonly planProjection = d('_id-planProjection');
  readonly ucofInput = d('id_use_card_on_file') as HTMLInputElement;
  readonly ccFieldset = d('_id-cardFieldset');
  readonly cardContainer = d('card-container');

  readonly receiptEmails = d('_id-receiptEmails') as HTMLTextAreaElement;
  readonly totalCost = d('_id-totalCost');
  readonly costBreakdown = d('_id-costBreakdown');

  readonly maxUsersElem = d('id_max_users') as HTMLInputElement | null;

  readonly planInfo: {[key: number]: Plan} = JSON.parse(this.planInfoElem.textContent);

  public maxUsers: number;

  updateMaxUsers(updatePlanInput: boolean = true) {
    if (this.maxUsersElem == null) return;
    this.maxUsers = parseInt(this.maxUsersElem.value);
    const minUsers = this.getPlan().minimum_users;
    this.maxUsersElem.min = `${minUsers}`;
    if (this.maxUsers < minUsers) {
      this.maxUsersElem.value = `${minUsers}`;
      this.maxUsers = minUsers;
    }
    if (updatePlanInput) this.updatePlanInput();
  }

  updateSavedCC(updatePlanInput: boolean = true) {
    if (this.ucofInput == null) {
      if (isFree(this.getPlan())) {
        if (this.cardContainer != null) {
          this.cardContainer.style.display = 'none';
        }
      } else {
        if (this.cardContainer != null) {
          this.cardContainer.style.display = '';
        }
      }
      return;
    }
    const ucofInput = document.querySelector(
      'input[name=use_card_on_file]:checked'
    ) as HTMLInputElement;
    if (ucofInput.value == 'True') {
      if (this.cardContainer != null) {
        // TODO: Use utility hide function
        this.cardContainer.style.display = 'none';
      }
    } else {
      if (this.cardContainer != null) {
        this.cardContainer.style.display = '';
      }
    }
    if (updatePlanInput) this.updatePlanInput();
  }

  constructor() {
    if (exists('id_max_users')) {
      // Handle reactive max user updates if field is defined.
      const maxUsersElem = this.maxUsersElem as HTMLInputElement;
      this.maxUsers = parseInt(maxUsersElem.value);
      on(maxUsersElem, 'input', () => {
        this.updateMaxUsers();
      });
      this.updateMaxUsers();
    } else {
      this.maxUsers = 1;
    }

    if (exists('id_use_card_on_file')) {
      on(this.ucofInput, 'input', () => this.updateSavedCC());
      this.updateSavedCC();
    }

    // Make receipt emails field auto-resize.
    this.receiptEmails.rows = 2;
    on(this.receiptEmails, 'input', () => this.receiptResize());
    this.receiptResize();
    // this.receiptEmails.setAttribute('resize', 'false');

    // Stripe and Mitch's code, largely unchanged.
    const stripe = Stripe(this.stripePk.value);
    const elements = stripe.elements();
    const style = {
      base: {
        color: '#3F3F3F',
        fontSize: '18px',
        fontFamily: 'system-ui, sans-serif',
        fontSmoothing: 'antialiased',
        '::placeholder': {
          color: '#899194',
        },
      },
      invalid: {
        color: '#e5424d',
        ':focus': {
          color: '#303238',
        },
      },
    };

    if (exists('card-element')) {
      // Decorate card.
      const card = elements.create('card', {style: style});
      card.mount('#card-element');
      card.addEventListener('change', event => {
        // Show Stripe errors.
        const displayError = document.getElementById('card-errors');
        if (event.error) {
          displayError.textContent = event.error.message;
        } else {
          displayError.textContent = '';
        }
      });

      // We don't want the browser to fill this in with old values
      (document.getElementById('id_stripe_token') as HTMLInputElement).value = '';

      // only show payment fields if needed

      this.planInput.addEventListener('input', () => {
        this.updateMaxUsers(false);
        this.updatePlanInput();
      });
      this.updatePlanInput();

      // Create a token or display an error when the form is submitted.
      const form = document.getElementById('stripe-form');
      form.addEventListener('submit', event => {
        const ucofInput = document.querySelector(
          'input[name=use_card_on_file]:checked'
        ) as HTMLInputElement;

        const useCardOnFile = ucofInput != null && ucofInput.value == 'True';
        const plan = this.planInfo[parseInt(this.planInput.value)];

        const isFreePlan = isFree(plan);
        if (!useCardOnFile && !isFreePlan) {
          event.preventDefault();

          stripe.createToken(card).then(function(result) {
            if (result.error) {
              // Inform the customer that there was an error.
              const errorElement = document.getElementById('card-errors');
              errorElement.textContent = result.error.message;
            } else {
              // Send the token to your server.
              stripeTokenHandler(result.token);
            }
          });
        }
      });
    }
  }

  receiptResize() {
    this.receiptEmails.style.height = '5px';
    this.receiptEmails.style.height = this.receiptEmails.scrollHeight + 'px';
  }

  getPlan(): Plan {
    return this.planInfo[parseInt(this.planInput.value)];
  }

  updateTotalCost() {
    const plan = this.getPlan();
    const cost = `${plan.base_price +
      (this.maxUsers - plan.minimum_users) * plan.price_per_user}`;
    const costFormatted = `$${cost}`;
    this.totalCost.textContent = costFormatted;

    let costBreakdownFormatted = `$${plan.base_price} (base price)`;
    if (this.maxUsers != 0) {
      if (this.maxUsers - plan.minimum_users == 0) {
        costBreakdownFormatted += ` with ${plan.minimum_users} user${
          plan.minimum_users != 1 ? 's' : ''
        } included`;
        if (plan.price_per_user != 0) {
          costBreakdownFormatted += `($${plan.price_per_user} per additional user)`;
        }
      } else {
        costBreakdownFormatted += ` with ${plan.minimum_users} user${
          plan.minimum_users != 1 ? 's' : ''
        } included and ${this.maxUsers - plan.minimum_users} extra users at $${
          plan.price_per_user
        } each`;
      }
    }
    this.costBreakdown.textContent = costBreakdownFormatted;
  }

  updatePlanInput() {
    const plan = this.getPlan();
    const isFreePlan = isFree(plan);

    this.updateTotalCost();

    // TODO: use util function for this display logic.
    if (isFreePlan) {
      if (this.ccFieldset != null) {
        this.ccFieldset.style.display = 'none';
      }
      if (this.planProjection != null) {
        this.planProjection.style.display = 'none';
      }
    } else {
      if (this.ccFieldset != null) {
        this.ccFieldset.style.display = '';
      }
      if (this.planProjection != null) {
        this.planProjection.style.display = '';
      }
    }
    this.updateSavedCC(false);
  }
}

function stripeTokenHandler(token) {
  // Insert the token ID into the form so it gets submitted to the server
  const hiddenInput = document.getElementById('id_stripe_token') as HTMLInputElement;
  hiddenInput.value = token.id;
  // Submit the form
  (document.getElementById('stripe-form') as HTMLFormElement).submit();
}
