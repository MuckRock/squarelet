import "@/css/plan.css"

// Stripe input styling
var cardInputStyle = {
  base: {
    backgroundColor: '#FFFFFF',
    color: '#3F3F3F',
    fontSize: '16px',
    fontFamily: '"Source Sans 3", "Source Sans Pro", system-ui, sans-serif',
    fontSmoothing: 'antialiased',
    '::placeholder': {
      color: '#899194',
    },
    padding: '0.25rem 0.5rem',
  },
  invalid: {
    color: '#e5424d',
    ':focus': {
      color: '#303238',
    },
  },
};

document.addEventListener("DOMContentLoaded", function () {
  // Make org cards data available to JavaScript
  const orgCards = JSON.parse(document.getElementById('org-card-data').textContent);
  const planData = JSON.parse(document.getElementById('plan-data').textContent);
  const cardFields = document.querySelectorAll(".card-field");
  cardFields.forEach((cardField) => {
    const form = cardField.closest('form');
    const stripePk = form.querySelector('#id_stripe_pk').value;
    const tokenInput = form.querySelector("#id_stripe_token");
    
    // Create the card element using the Stripe public key
    const stripe = Stripe(stripePk);
    const elements = stripe.elements();
    const cardElement = elements.create("card", {style: cardInputStyle });
    const cardElementMount = cardField.querySelector(".card-element");
    cardElement.mount(cardElementMount);
    
    // Handle real-time validation errors from the card element
    cardElement.on("change", function (event) {
      const displayError = cardField.querySelector(".card-element-errors");
      if (event.error) {
        displayError.textContent = event.error.message;
      } else {
        displayError.textContent = "";
      }
    });
    
    // We don't want the browser to fill this in with old values
    tokenInput.value = "";
    
    // Create a token or display an error when submitting the form
    form.addEventListener("submit", function(event) {
      event.preventDefault();
      if (tokenInput.value) {
        // Token already exists, continue with normal submission
        return true;
      }
      const payMethodInput = document.querySelector(
        "input[name=payment_method]:checked",
      );
      if (payMethodInput != null && payMethodInput.value == "existing") {
        // Do not try to get token if using a card on file
        form.submit();
        /* Skip until #461
      } else if (payMethodInput != null && payMethodInput.value == "invoice") {
        // Do not try to get token if paying by invoice
        form.submit();
        */
      } else {
        stripe.createToken(cardElement).then(function(result) {
          if (result.error) {
            // Inform the customer that there was an error
            const displayError = cardField.querySelector(".card-element-errors");
            displayError.textContent = result.error.message;
          } else {
            // Set the token value and submit the form
            tokenInput.value = result.token.id;
            form.submit();
          }
        });
      }
    });
  });
  
  // Helper functions for organization selection
  function getFormElements(form) {
    return {
      cardOnFileOptions: form.querySelectorAll('.card-on-file-option'),
      cardField: form.querySelector('.card-field'),
      paymentMethods: form.querySelector('.payment-methods'),
      saveCardCheckbox: form.querySelector('input[name="save_card"]').closest('label'),
      existingCardRadio: form.querySelector('input[value="existing"]'),
      newCardRadio: form.querySelector('input[value="new"]'),
      managePaymentLink: form.querySelector('.manage-payment-link'),
      newOrgInput: form.querySelector('#id_new_organization_name'),
      newOrgField: form.querySelector('#id_new_organization_name')?.closest('label'),
      submitButton: form.querySelector('button[type="submit"]')
    };
  }
  
  function updateManagePaymentLink(selectElement, managePaymentLink) {
    const selectedOption = selectElement.options[selectElement.selectedIndex];
    const isIndividual = selectedOption.getAttribute('data-individual') === 'true';
    const orgSlug = selectedOption.getAttribute('data-slug');

    if (isIndividual) {
      managePaymentLink.href = '/users/~payment/';
    } else if (orgSlug) {
      managePaymentLink.href = `/organizations/${orgSlug}/payment/`;
    }

    // Only show the link if there's a valid org (not "new" or empty)
    if (orgSlug) {
      managePaymentLink.style.display = 'inline-block';
    } else {
      managePaymentLink.style.display = 'none';
    }
  }
  
  function updateCardOptions(selectedOrg, elements) {
    const { cardOnFileOptions, existingCardRadio, newCardRadio } = elements;
    // const invoiceRadio = document.querySelector('input[value="invoice"]');
    const orgHasCard = orgCards[selectedOrg];
    // const noSelection = !existingCardRadio.checked && !newCardRadio.checked && !(invoiceRadio && invoiceRadio.checked);
    const noSelection = !existingCardRadio.checked && !newCardRadio.checked;

    if (orgHasCard) {
      // Show existing card option and update card info
      cardOnFileOptions.forEach(option => {
        option.style.display = 'block';
        const cardInfo = option.querySelector('.card-info');
        if (cardInfo) {
          cardInfo.textContent = `Use existing ${orgCards[selectedOrg].brand} ending in ${orgCards[selectedOrg].last4}`;
        }
      });

      // Default to existing card if no selection made
      if (noSelection) {
        existingCardRadio.checked = true;
      }

      // Remove only-option class if it exists
      const newCardOption = newCardRadio?.closest('.new-card-option');
      if (newCardOption) {
        newCardOption.classList.remove('only-option');
      }
    } else {
      // Hide existing card option
      cardOnFileOptions.forEach(option => option.style.display = 'none');

      // Switch to new card if existing was selected but not available
      // Default to new card if no selection made
      if (existingCardRadio.checked || noSelection) {
          newCardRadio.checked = true;
      }

      // Hide the radio button when it's the only option
      const newCardOption = newCardRadio?.closest('.new-card-option');
      if (newCardOption) {
        newCardOption.classList.add('only-option');
      }
    }
  }
  
  function updatePaymentUI(elements) {
    const { cardField, saveCardCheckbox, existingCardRadio, newCardRadio } = elements;
    // const invoiceRadio = document.querySelector('input[value="invoice"]');

    if (existingCardRadio.checked) {
      cardField.style.display = 'none';
      saveCardCheckbox.style.display = 'none';
    } else if (newCardRadio.checked) {
      cardField.style.display = 'block';
      saveCardCheckbox.style.display = 'block';
    }
    /* Skip until #461
    } else if (invoiceRadio && invoiceRadio.checked) {
      cardField.style.display = 'none';
      saveCardCheckbox.style.display = 'none';
    }
    */
  }
  
  function hideAllPaymentElements(elements) {
    const { paymentMethods, cardField, saveCardCheckbox, managePaymentLink } = elements;

    paymentMethods.style.display = 'none';
    cardField.style.display = 'none';
    saveCardCheckbox.style.display = 'none';
    managePaymentLink.style.display = 'none';
  }

  function toggleNewOrgField(selectedOrg: string, elements: Record<string, HTMLInputElement>) {
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

  function updateSubmitButton(selectedOrg: string, elements: Record<string, any>) {
    const { submitButton } = elements;

    if (!submitButton) return;

    // Enable the button when an organization is selected
    if (selectedOrg && selectedOrg !== '') {
      (submitButton as HTMLButtonElement).disabled = false;
    } else {
      (submitButton as HTMLButtonElement).disabled = true;
    }
  }
  
  // Organization selection handling
  const orgSelects = document.querySelectorAll('.org-select');
  orgSelects.forEach(select => {
    select.addEventListener('change', function() {
      const form = this.closest('form');
      const selectedOrg = this.value;
      const elements = getFormElements(form);

      if (selectedOrg) {
        // Toggle new organization name field
        toggleNewOrgField(selectedOrg, elements);

        // Show payment methods section
        elements.paymentMethods.style.display = 'block';

        // Update manage payment methods link
        updateManagePaymentLink(this, elements.managePaymentLink);

        // Update card options based on organization
        updateCardOptions(selectedOrg, elements);

        // Update UI based on current payment method selection
        updatePaymentUI(elements);

        // Enable the submit button
        updateSubmitButton(selectedOrg, elements);
      } else {
        // No organization selected - hide everything
        toggleNewOrgField(selectedOrg, elements);
        hideAllPaymentElements(elements);

        // Disable the submit button
        updateSubmitButton(selectedOrg, elements);
      }
    });
    select.dispatchEvent(new Event("change"));
  });
  
  // Payment method selection handling
  const paymentMethodRadios = document.querySelectorAll('input[name="payment_method"]');
  paymentMethodRadios.forEach(radio => {
    radio.addEventListener('change', function() {
      const form = this.closest('form');
      const elements = getFormElements(form);
      
      updatePaymentUI(elements);
    });
    radio.dispatchEvent(new Event("change"));
  });
});
