import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Stripe API Mocks
interface MockStripeElement {
  mount: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  unmount: ReturnType<typeof vi.fn>;
}

interface MockStripeElements {
  create: ReturnType<typeof vi.fn>;
}

interface MockStripe {
  elements: ReturnType<typeof vi.fn>;
  createToken: ReturnType<typeof vi.fn>;
}

const createMockStripeElement = (): MockStripeElement => ({
  mount: vi.fn(),
  on: vi.fn(),
  unmount: vi.fn(),
});

const createMockStripeElements = (mockElement: MockStripeElement): MockStripeElements => ({
  create: vi.fn(() => mockElement),
});

const createMockStripe = (mockElements: MockStripeElements): MockStripe => ({
  elements: vi.fn(() => mockElements),
  createToken: vi.fn(() => Promise.resolve({
    token: { id: 'tok_test123' }
  })),
});

// DOM Fixture Helpers
function createOrgCardData(hasCard: boolean = false) {
  return JSON.stringify(hasCard ? {
    'org-1': { brand: 'Visa', last4: '4242' },
    'individual': { brand: 'Mastercard', last4: '5555' }
  } : {});
}

function createPlanData() {
  return JSON.stringify({
    name: 'Professional',
    price: 20
  });
}

function createFormFixture(options: {
  hasCardOnFile?: boolean;
  includeInvoiceOption?: boolean;
  selectedOrg?: string;
} = {}) {
  const {
    hasCardOnFile = false,
    includeInvoiceOption = false,
    selectedOrg = ''
  } = options;

  // Don't pre-select new card if organization has card on file
  // This allows the code to auto-select the existing card
  const newCardChecked = hasCardOnFile ? '' : 'checked';

  return `
    <script id="org-card-data" type="application/json">${createOrgCardData(hasCardOnFile)}</script>
    <script id="plan-data" type="application/json">${createPlanData()}</script>

    <form id="test-form">
      <input type="hidden" id="id_stripe_pk" value="pk_test_123" />
      <input type="hidden" id="id_stripe_token" name="stripe_token" />

      <select class="org-select" name="organization">
        <option value="">Select an organization</option>
        <option value="org-1" data-slug="org-1" data-individual="false" ${selectedOrg === 'org-1' ? 'selected' : ''}>Test Org</option>
        <option value="individual" data-slug="individual" data-individual="true" ${selectedOrg === 'individual' ? 'selected' : ''}>Individual</option>
        <option value="new">Create New Organization</option>
      </select>

      <label for="id_new_organization_name">
        <input type="text" id="id_new_organization_name" name="new_organization_name" />
      </label>

      <div class="payment-methods" style="display: none;">
        <div class="card-on-file-option" style="display: none;">
          <input type="radio" name="payment_method" value="existing-card" id="id_existing_card" />
          <label for="id_existing_card">
            <span class="card-info"></span>
          </label>
        </div>

        <div class="new-card-option">
          <input type="radio" name="payment_method" value="new-card" id="id_new_card" ${newCardChecked} />
          <label for="id_new_card">Use a new card</label>
        </div>

        ${includeInvoiceOption ? `
          <div class="invoice-option">
            <input type="radio" name="payment_method" value="invoice" id="id_invoice" />
            <label for="id_invoice">Pay by invoice</label>
          </div>
        ` : ''}
      </div>

      <div class="card-field" style="display: none;">
        <div class="card-element"></div>
        <div class="card-element-errors"></div>
      </div>

      <label style="display: none;">
        <input type="checkbox" name="save_card" />
        Save card for future use
      </label>

      <a href="#" class="manage-payment-link" style="display: none;">Manage payment methods</a>

      <button type="submit" disabled>Subscribe</button>
    </form>
  `;
}

// Test Suite
describe('Plan View - Payment Form Logic', () => {
  let mockElement: MockStripeElement;
  let mockElements: MockStripeElements;
  let mockStripe: MockStripe;

  beforeEach(() => {
    // Set up Stripe mocks
    mockElement = createMockStripeElement();
    mockElements = createMockStripeElements(mockElement);
    mockStripe = createMockStripe(mockElements);

    // @ts-ignore - Mock global Stripe
    global.Stripe = vi.fn(() => mockStripe);

    // Clear the DOM
    document.body.innerHTML = '';
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  const loadModule = async () => {
    // Import the module which will execute the DOMContentLoaded listener
    await import('./plan');
    // Trigger DOMContentLoaded
    document.dispatchEvent(new Event('DOMContentLoaded'));
  };

  describe('Organization Selection', () => {
    it('should handle organization selection changes', async () => {
      document.body.innerHTML = createFormFixture();
      await loadModule();

      const select = document.querySelector('.org-select') as HTMLSelectElement;
      const paymentMethods = document.querySelector('.payment-methods') as HTMLDivElement;
      const submitButton = document.querySelector('button[type="submit"]') as HTMLButtonElement;

      expect(paymentMethods.style.display).toBe('none');
      expect(submitButton.disabled).toBe(true);

      select.value = 'org-1';
      select.dispatchEvent(new Event('change'));

      expect(paymentMethods.style.display).toBe('block');
      expect(submitButton.disabled).toBe(false);
    });

    it('should toggle new organization name field when "new" is selected', async () => {
      document.body.innerHTML = createFormFixture();
      await loadModule();

      const select = document.querySelector('.org-select') as HTMLSelectElement;
      const newOrgField = document.querySelector('#id_new_organization_name')?.closest('label') as HTMLLabelElement;
      const newOrgInput = document.querySelector('#id_new_organization_name') as HTMLInputElement;

      expect(newOrgField.classList.contains('showField')).toBe(false);
      expect(newOrgInput.required).toBe(false);

      select.value = 'new';
      select.dispatchEvent(new Event('change'));

      expect(newOrgField.classList.contains('showField')).toBe(true);
      expect(newOrgInput.required).toBe(true);

      select.value = 'org-1';
      select.dispatchEvent(new Event('change'));

      expect(newOrgField.classList.contains('showField')).toBe(false);
      expect(newOrgInput.required).toBe(false);
      expect(newOrgInput.value).toBe('');
    });

    it('should update manage payment link based on organization selection', async () => {
      document.body.innerHTML = createFormFixture();
      await loadModule();

      const select = document.querySelector('.org-select') as HTMLSelectElement;
      const manageLink = document.querySelector('.manage-payment-link') as HTMLAnchorElement;

      select.value = 'org-1';
      select.dispatchEvent(new Event('change'));

      expect(manageLink.href).toContain('/organizations/org-1/payment/');
      expect(manageLink.style.display).toBe('inline-block');

      select.value = 'individual';
      select.dispatchEvent(new Event('change'));

      expect(manageLink.href).toContain('/users/~payment/');
      expect(manageLink.style.display).toBe('inline-block');

      select.value = 'new';
      select.dispatchEvent(new Event('change'));

      expect(manageLink.style.display).toBe('none');
    });
  });

  describe('Payment Method Options', () => {
    it('should toggle payment method options based on selected organization', async () => {
      document.body.innerHTML = createFormFixture({ hasCardOnFile: true });
      await loadModule();

      const select = document.querySelector('.org-select') as HTMLSelectElement;
      const cardOnFileOption = document.querySelector('.card-on-file-option') as HTMLDivElement;
      const existingCardRadio = document.querySelector('input[value="existing-card"]') as HTMLInputElement;

      select.value = 'org-1';
      select.dispatchEvent(new Event('change'));

      expect(cardOnFileOption.style.display).toBe('block');
      expect(existingCardRadio.checked).toBe(true);

      const cardInfo = cardOnFileOption.querySelector('.card-info');
      expect(cardInfo?.textContent).toContain('Visa');
      expect(cardInfo?.textContent).toContain('4242');
    });

    it('should handle existing card vs new card selection', async () => {
      document.body.innerHTML = createFormFixture({ hasCardOnFile: true });
      await loadModule();

      const select = document.querySelector('.org-select') as HTMLSelectElement;
      const existingCardRadio = document.querySelector('input[value="existing-card"]') as HTMLInputElement;
      const newCardRadio = document.querySelector('input[value="new-card"]') as HTMLInputElement;
      const cardField = document.querySelector('.card-field') as HTMLDivElement;
      const saveCardCheckbox = document.querySelector('input[name="save_card"]')?.closest('label') as HTMLLabelElement;

      select.value = 'org-1';
      select.dispatchEvent(new Event('change'));

      expect(existingCardRadio.checked).toBe(true);
      expect(cardField.style.display).toBe('none');
      expect(saveCardCheckbox.style.display).toBe('none');

      newCardRadio.checked = true;
      newCardRadio.dispatchEvent(new Event('change'));

      expect(cardField.style.display).toBe('block');
      expect(saveCardCheckbox.style.display).toBe('block');
    });

    it('should show/hide card input based on payment method selection', async () => {
      document.body.innerHTML = createFormFixture({ includeInvoiceOption: true });
      await loadModule();

      const select = document.querySelector('.org-select') as HTMLSelectElement;
      const newCardRadio = document.querySelector('input[value="new-card"]') as HTMLInputElement;
      const invoiceRadio = document.querySelector('input[value="invoice"]') as HTMLInputElement;
      const cardField = document.querySelector('.card-field') as HTMLDivElement;
      const saveCardCheckbox = document.querySelector('input[name="save_card"]')?.closest('label') as HTMLLabelElement;

      select.value = 'org-1';
      select.dispatchEvent(new Event('change'));

      newCardRadio.checked = true;
      newCardRadio.dispatchEvent(new Event('change'));

      expect(cardField.style.display).toBe('block');
      expect(saveCardCheckbox.style.display).toBe('block');

      invoiceRadio.checked = true;
      invoiceRadio.dispatchEvent(new Event('change'));

      expect(cardField.style.display).toBe('none');
      expect(saveCardCheckbox.style.display).toBe('none');
    });
  });

  describe('Stripe Integration', () => {
    it('should initialize Stripe card element on DOMContentLoaded', async () => {
      document.body.innerHTML = createFormFixture();
      await loadModule();

      expect(global.Stripe).toHaveBeenCalledWith('pk_test_123');
      expect(mockStripe.elements).toHaveBeenCalled();
      expect(mockElements.create).toHaveBeenCalledWith('card', expect.objectContaining({
        style: expect.any(Object)
      }));
      expect(mockElement.mount).toHaveBeenCalled();
    });

    it('should validate card input and display errors', async () => {
      document.body.innerHTML = createFormFixture();
      await loadModule();

      const errorDiv = document.querySelector('.card-element-errors') as HTMLDivElement;

      // Get the change handler that was registered
      const changeHandler = mockElement.on.mock.calls.find(call => call[0] === 'change')?.[1];
      expect(changeHandler).toBeDefined();

      // Simulate error event
      changeHandler({ error: { message: 'Card number is invalid' } });
      expect(errorDiv.textContent).toBe('Card number is invalid');

      // Simulate success event
      changeHandler({ error: null });
      expect(errorDiv.textContent).toBe('');
    });

    it('should handle Stripe token creation on form submission', async () => {
      document.body.innerHTML = createFormFixture();
      await loadModule();

      const form = document.querySelector('form') as HTMLFormElement;
      const select = document.querySelector('.org-select') as HTMLSelectElement;
      const tokenInput = document.querySelector('#id_stripe_token') as HTMLInputElement;
      const formSubmitSpy = vi.spyOn(form, 'submit').mockImplementation(() => {});

      // Select an organization and new card payment method
      select.value = 'org-1';
      select.dispatchEvent(new Event('change'));

      const newCardRadio = document.querySelector('input[value="new-card"]') as HTMLInputElement;
      newCardRadio.checked = true;

      // Submit the form
      form.dispatchEvent(new Event('submit'));

      // Wait for async token creation
      await new Promise(resolve => setTimeout(resolve, 0));

      expect(mockStripe.createToken).toHaveBeenCalledWith(mockElement);
      expect(tokenInput.value).toBe('tok_test123');
      expect(formSubmitSpy).toHaveBeenCalled();

      formSubmitSpy.mockRestore();
    });

    it('should skip token creation when using existing card', async () => {
      document.body.innerHTML = createFormFixture({ hasCardOnFile: true });
      await loadModule();

      const form = document.querySelector('form') as HTMLFormElement;
      const select = document.querySelector('.org-select') as HTMLSelectElement;
      const formSubmitSpy = vi.spyOn(form, 'submit').mockImplementation(() => {});

      select.value = 'org-1';
      select.dispatchEvent(new Event('change'));

      const existingCardRadio = document.querySelector('input[value="existing-card"]') as HTMLInputElement;
      expect(existingCardRadio.checked).toBe(true);

      form.dispatchEvent(new Event('submit'));

      await new Promise(resolve => setTimeout(resolve, 0));

      expect(mockStripe.createToken).not.toHaveBeenCalled();
      expect(formSubmitSpy).toHaveBeenCalled();

      formSubmitSpy.mockRestore();
    });

    it('should display token creation errors', async () => {
      document.body.innerHTML = createFormFixture();

      // Mock token creation to return an error
      mockStripe.createToken = vi.fn(() => Promise.resolve({
        error: { message: 'Token creation failed' }
      }));

      await loadModule();

      const form = document.querySelector('form') as HTMLFormElement;
      const select = document.querySelector('.org-select') as HTMLSelectElement;
      const errorDiv = document.querySelector('.card-element-errors') as HTMLDivElement;
      const formSubmitSpy = vi.spyOn(form, 'submit').mockImplementation(() => {});

      select.value = 'org-1';
      select.dispatchEvent(new Event('change'));

      form.dispatchEvent(new Event('submit'));

      await new Promise(resolve => setTimeout(resolve, 0));

      expect(errorDiv.textContent).toBe('Token creation failed');
      expect(formSubmitSpy).not.toHaveBeenCalled();

      formSubmitSpy.mockRestore();
    });
  });

  describe('Submit Button State', () => {
    it('should enable/disable submit button based on form validity', async () => {
      document.body.innerHTML = createFormFixture();
      await loadModule();

      const select = document.querySelector('.org-select') as HTMLSelectElement;
      const submitButton = document.querySelector('button[type="submit"]') as HTMLButtonElement;

      expect(submitButton.disabled).toBe(true);

      select.value = 'org-1';
      select.dispatchEvent(new Event('change'));

      expect(submitButton.disabled).toBe(false);

      select.value = '';
      select.dispatchEvent(new Event('change'));

      expect(submitButton.disabled).toBe(true);
    });
  });
});
