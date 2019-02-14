
function stripeTokenHandler(token) {
  // Insert the token ID into the form so it gets submitted to the server
  var hiddenInput = document.getElementById("id_stripe_token");
  hiddenInput.value = token.id;
  // Submit the form
  document.getElementById("stripe-form").submit();
}

document.addEventListener("DOMContentLoaded", function() {
  var stripe = Stripe(document.getElementById('id_stripe_pk').value);
  var elements = stripe.elements();
  var style = {
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
  if (document.getElementById("card-element")) {
    var card = elements.create('card', {style: style});
    card.mount('#card-element');
    card.addEventListener('change', function(event) {
      var displayError = document.getElementById('card-errors');
      if (event.error) {
        displayError.textContent = event.error.message;
      } else {
        displayError.textContent = '';
      }
    });
    // We don't want the browser to fill this in with old values
    document.getElementById("id_stripe_token").value = "";
    // only show payment fields if needed
    var planInput = document.getElementById('id_plan');
    var freeChoices = JSON.parse(document.getElementById('free-choices').textContent);
    planInput.addEventListener('change', function() {
      var isFreePlan = freeChoices.indexOf(parseInt(this.value)) >= 0;
      var ucofInput = document.getElementById('id_use_card_on_file');
      var cardContainer = document.getElementById('card-container');
      if (isFreePlan) {
        if (ucofInput) { ucofInput.parentNode.style.display = 'none'; }
        if (cardContainer) { cardContainer.style.display = 'none'; }
      } else {
        if (ucofInput) { ucofInput.parentNode.style.display = ''; }
        if (cardContainer) { cardContainer.style.display = ''; }
      }
    });
    planInput.dispatchEvent(new Event('change'));
    // Create a token or display an error when the form is submitted.
    var form = document.getElementById('stripe-form');
    form.addEventListener('submit', function(event) {
      var ucofInput = document.querySelector(
        "input[name=use_card_on_file]:checked");
      var useCardOnFile = ucofInput && ucofInput.value === "True";
      console.log(freeChoices);
      var isFreePlan = freeChoices.indexOf(parseInt(planInput.value)) >= 0;
      console.log(isFreePlan);
      if (!useCardOnFile && !isFreePlan) {
        event.preventDefault();

        stripe.createToken(card).then(function(result) {
          if (result.error) {
            // Inform the customer that there was an error.
            var errorElement = document.getElementById('card-errors');
            errorElement.textContent = result.error.message;
          } else {
            // Send the token to your server.
            stripeTokenHandler(result.token);
          }
        });
      }
    });
  }
});
