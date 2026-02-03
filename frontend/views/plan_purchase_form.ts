import "@/css/plan_purchase_form.css"

// Helper function to format numbers with commas
function formatPrice(price: number): string {
  return price.toLocaleString('en-US');
}

// Stripe input styling
const cardInputStyle = {
  base: {
    backgroundColor: '#FFFFFF',
    color: '#3F3F3F',
    fontSize: '16px',
    fontFamily: '"Source Sans 3", "Source Sans Pro", system-ui, sans-serif',
    fontSmoothing: 'antialiased',
    '::placeholder': {
      color: '#899194',
    }
  },
  invalid: {
    color: '#e5424d',
    ':focus': {
      color: '#303238',
    },
  },
};

interface OrgCard {
  last4: string;
  brand: string;
}

interface OrgCards {
  [orgId: string]: OrgCard;
}

interface PlanData {
  annual: boolean;
  is_sunlight_plan: boolean;
  base_price: number;
  price_per_user: number;
  minimum_users: number;
  has_nonprofit_variant?: boolean;
  nonprofit_base_price?: number;
  nonprofit_price_per_user?: number;
}

interface FormElements {
  cardOnFileOption: HTMLDivElement | null;
  cardField: HTMLDivElement | null;
  paymentMethods: HTMLDivElement | null;
  saveCardCheckbox: HTMLLabelElement | null;
  existingCardRadio: HTMLInputElement | null;
  newCardRadio: HTMLInputElement | null;
  invoiceRadio: HTMLInputElement | null;
  managePaymentLink: HTMLAnchorElement | null;
  newOrgInput: HTMLInputElement | null;
  newOrgField: HTMLLabelElement | null;
  submitButton: HTMLButtonElement | null;
  nonprofitCheckbox: HTMLInputElement | null;
  nonprofitContainer: HTMLDivElement | null;
  originalPrice: HTMLSpanElement | null;
  discountedPrice: HTMLSpanElement | null;
}

/**
 * Initialize a plan purchase form instance
 */
function initPlanPurchaseForm(container: HTMLElement): void {
  // Get data from JSON script tags within this container
  const orgCardsScript = container.querySelector('#org-card-data');
  const planDataScript = container.querySelector('#plan-data');

  const orgCards: OrgCards = orgCardsScript
    ? JSON.parse(orgCardsScript.textContent || '{}')
    : {};
  const planData: PlanData = planDataScript
    ? JSON.parse(planDataScript.textContent || '{}')
    : {};

  // Find the parent form element
  const form = container.closest('form') as HTMLFormElement;
  if (!form) return;

  // Initialize Stripe if we have the necessary elements
  const stripePkInput = form.querySelector('#id_stripe_pk') as HTMLInputElement;
  const tokenInput = form.querySelector('#id_stripe_token') as HTMLInputElement;
  const cardField = container.querySelector('.card-field') as HTMLDivElement;

  let cardElement: any = null;
  let stripe: any = null;

  if (stripePkInput && tokenInput && cardField) {
    const stripePk = stripePkInput.value;
    stripe = (window as any).Stripe(stripePk);
    const elements = stripe.elements();
    cardElement = elements.create('card', { style: cardInputStyle });
    const cardElementMount = cardField.querySelector('.card-element');
    if (cardElementMount) {
      cardElement.mount(cardElementMount);
    }

    // Handle real-time validation errors from the card element
    cardElement.on('change', function(event: any) {
      const displayError = cardField.querySelector('.card-element-errors');
      if (displayError) {
        displayError.textContent = event.error ? event.error.message : '';
      }
    });

    // Clear token input
    tokenInput.value = '';
  }

  // Get form elements
  function getFormElements(): FormElements {
    return {
      cardOnFileOption: container.querySelector('.card-on-file-option'),
      cardField: container.querySelector('.card-field'),
      paymentMethods: container.querySelector('.payment-methods'),
      saveCardCheckbox: container.querySelector('.save-card-option'),
      existingCardRadio: container.querySelector('input[value="existing-card"]'),
      newCardRadio: container.querySelector('input[value="new-card"]'),
      invoiceRadio: container.querySelector('input[value="invoice"]'),
      managePaymentLink: container.querySelector('.manage-payment-link'),
      newOrgInput: container.querySelector('#id_new_organization_name'),
      newOrgField: container.querySelector('#id_new_organization_name')?.closest('label') as HTMLLabelElement | null,
      submitButton: form.querySelector('button[type="submit"]'),
      nonprofitCheckbox: container.querySelector('#id_is_nonprofit'),
      nonprofitContainer: container.querySelector('.nonprofit-checkbox'),
      originalPrice: form.querySelector('.original-price'),
      discountedPrice: form.querySelector('.discounted-price'),
    };
  }

  function updateManagePaymentLink(selectElement: HTMLSelectElement, managePaymentLink: HTMLAnchorElement): void {
    const selectedOption = selectElement.options[selectElement.selectedIndex];
    const isIndividual = selectedOption.getAttribute('data-individual') === 'true';
    const orgSlug = selectedOption.getAttribute('data-slug');

    if (isIndividual) {
      managePaymentLink.href = '/users/~payment/';
    } else if (orgSlug) {
      managePaymentLink.href = `/organizations/${orgSlug}/payment/`;
    }

    // Only show the link if there's a valid org (not "new" or empty)
    managePaymentLink.style.display = orgSlug ? 'inline-block' : 'none';
  }

  function updateCardOptions(selectedOrg: string, elements: FormElements): void {
    const { cardOnFileOption, existingCardRadio, newCardRadio, invoiceRadio } = elements;
    if (!cardOnFileOption || !existingCardRadio || !newCardRadio) return;

    const orgHasCard = Object.hasOwn(orgCards, selectedOrg) ? orgCards[selectedOrg] : null;
    const noSelection = !existingCardRadio.checked && !newCardRadio.checked && !(invoiceRadio && invoiceRadio.checked);
    if (orgHasCard && cardOnFileOption) {
      // Show existing card option and update card info
      cardOnFileOption.style.display = 'block';
      const cardInfo = cardOnFileOption.querySelector('.card-info');
      if (cardInfo) {
        cardInfo.textContent = `Use existing ${orgCards[selectedOrg].brand} ending in ${orgCards[selectedOrg].last4}`;
      }

      // Default to existing card if no selection made
      if (noSelection) {
        existingCardRadio.checked = true;
      }

      // Remove only-option class if it exists
      const newCardOption = newCardRadio?.closest('.new-card-option');
      if (newCardOption) {
        newCardOption.classList.remove('only-option');
      }
    } else if (cardOnFileOption) {
      // Hide existing card option
      cardOnFileOption.style.display = 'none';

      // Switch to new card if existing was selected but not available
      // Default to new card if no selection made
      if (existingCardRadio.checked || noSelection) {
        newCardRadio.checked = true;
      }
    }
  }

  function updatePaymentUI(elements: FormElements): void {
    const { cardField, saveCardCheckbox, existingCardRadio, newCardRadio, invoiceRadio } = elements;
    if (!cardField || !saveCardCheckbox) return;

    if (existingCardRadio?.checked) {
      cardField.style.display = 'none';
      saveCardCheckbox.style.display = 'none';
    } else if (newCardRadio?.checked) {
      cardField.style.display = 'block';
      saveCardCheckbox.style.display = 'block';
    } else if (invoiceRadio?.checked) {
      cardField.style.display = 'none';
      saveCardCheckbox.style.display = 'none';
    }
  }

  function hideAllPaymentElements(elements: FormElements): void {
    const { paymentMethods, cardField, saveCardCheckbox, managePaymentLink } = elements;

    if (paymentMethods) paymentMethods.style.display = 'none';
    if (cardField) cardField.style.display = 'none';
    if (saveCardCheckbox) saveCardCheckbox.style.display = 'none';
    if (managePaymentLink) managePaymentLink.style.display = 'none';
  }

  function toggleNewOrgField(selectedOrg: string, elements: FormElements): void {
    const { newOrgField, newOrgInput } = elements;
    if (!newOrgField || !newOrgInput) return;

    if (selectedOrg === 'new') {
      newOrgField.classList.add('showField');
      newOrgInput.required = true;
    } else {
      newOrgField.classList.remove('showField');
      newOrgInput.required = false;
      newOrgInput.value = ''; // Clear the value when hidden
    }
  }

  function updateSubmitButton(selectedOrg: string, elements: FormElements): void {
    const { submitButton } = elements;
    if (!submitButton) return;

    // Enable the button when an organization is selected
    submitButton.disabled = !selectedOrg || selectedOrg === '';
  }

  function updatePriceDisplay(elements: FormElements): void {
    const { nonprofitCheckbox, originalPrice, discountedPrice } = elements;
    if (!nonprofitCheckbox || !originalPrice || !discountedPrice) return;

    if (nonprofitCheckbox.checked && planData.has_nonprofit_variant) {
      // Show discounted price from nonprofit plan variant
      originalPrice.style.textDecoration = 'line-through';
      originalPrice.style.opacity = '0.6';
      discountedPrice.textContent = `$${formatPrice(planData.nonprofit_base_price || 0)}`;
      discountedPrice.style.display = 'inline';
    } else {
      // Show normal price
      discountedPrice.style.display = 'none';
      originalPrice.style.textDecoration = 'none';
      originalPrice.style.opacity = '1';
    }
  }

  // Organization selection handling
  const orgSelect = container.querySelector('.org-select') as HTMLSelectElement;
  if (orgSelect) {
    orgSelect.addEventListener('change', function() {
      const selectedOrg = this.value;
      const elements = getFormElements();

      if (selectedOrg) {
        // Toggle new organization name field
        toggleNewOrgField(selectedOrg, elements);

        // Show payment methods section
        if (elements.paymentMethods) {
          elements.paymentMethods.style.display = 'block';
        }

        // Update manage payment methods link
        if (elements.managePaymentLink) {
          updateManagePaymentLink(this, elements.managePaymentLink);
        }

        // Update card options based on organization
        updateCardOptions(selectedOrg, elements);

        // Update UI based on current payment method selection
        updatePaymentUI(elements);

        // Enable the submit button
        updateSubmitButton(selectedOrg, elements);

        // Update price display for nonprofit checkbox
        updatePriceDisplay(elements);
      } else {
        // No organization selected - hide everything
        toggleNewOrgField(selectedOrg, elements);
        hideAllPaymentElements(elements);

        // Disable the submit button
        updateSubmitButton(selectedOrg, elements);
      }
    });

    // Trigger initial state
    orgSelect.dispatchEvent(new Event('change'));
  }

  // Payment method selection handling
  const paymentMethodRadios = container.querySelectorAll('input[name="payment_method"]');
  paymentMethodRadios.forEach(radio => {
    radio.addEventListener('change', function() {
      const elements = getFormElements();
      updatePaymentUI(elements);
    });
  });

  // Nonprofit checkbox handling
  const nonprofitCheckbox = container.querySelector('#id_is_nonprofit') as HTMLInputElement;
  if (nonprofitCheckbox) {
    nonprofitCheckbox.addEventListener('change', function() {
      const elements = getFormElements();
      updatePriceDisplay(elements);
    });
  }

  // Form submission handling with Stripe
  if (stripe && cardElement && tokenInput) {
    form.addEventListener('submit', function(event) {
      event.preventDefault();

      if (tokenInput.value) {
        // Token already exists, continue with normal submission
        form.submit();
        return;
      }

      const payMethodInput = container.querySelector(
        'input[name=payment_method]:checked'
      ) as HTMLInputElement;

      if (
        payMethodInput != null &&
        (['existing-card', 'invoice'].includes(payMethodInput.value))
      ) {
        // Do not try to get token if using a card on file or invoice
        form.submit();
      } else {
        stripe.createToken(cardElement).then(function(result: any) {
          if (result.error) {
            // Inform the customer that there was an error
            const displayError = cardField?.querySelector('.card-element-errors');
            if (displayError) {
              displayError.textContent = result.error.message;
            }
          } else {
            // Set the token value and submit the form
            tokenInput.value = result.token.id;
            form.submit();
          }
        });
      }
    });
  }
}

// Initialize all plan purchase forms on page load
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('[data-plan-purchase-form]').forEach((formElement) => {
    initPlanPurchaseForm(formElement as HTMLElement);
  });
});
