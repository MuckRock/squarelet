/**
 * Alerts
 *
 * Provides progressive enhancement for server-rendered alerts and
 * allows dynamic creation of client-side alerts.
 */

import './css/alerts.css';

export type AlertType = 'success' | 'error' | 'warning' | 'info' | 'debug';

export interface AlertOptions {
  canDismiss?: boolean;
  autoDismiss?: boolean;
  duration?: number; // milliseconds
}

const DEFAULT_OPTIONS: AlertOptions = {
  canDismiss: true,
  autoDismiss: true,
  duration: 5000, // 5 seconds
};

// Store cleanup functions for each alert element
const alertCleanups = new WeakMap<HTMLElement, () => void>();

/**
 * Initialize the alert system by enhancing existing server-rendered alerts
 * with dismiss handlers and auto-dismiss timers.
 */
export function initAlerts(): void {
  // Find all existing alerts on the page
  const alerts = document.querySelectorAll('._cls-alert');

  alerts.forEach((alertContainer) => {
    const alertElement = alertContainer.querySelector('div[class^="alert-"]') as HTMLElement;
    if (alertElement) {
      // Check if auto-dismiss is enabled for this alert
      const autoDismiss = alertElement.hasAttribute('data-auto-dismiss');
      const dismissButton = alertElement.querySelector('[data-dismiss="alert"]') as HTMLElement;

      // Set up dismiss button handler
      if (dismissButton) {
        dismissButton.addEventListener('click', (e) => {
          e.preventDefault();
          dismissAlert(dismissButton);
        });
      }
      // Set up auto-dismiss for server-rendered alerts (if enabled)
      if (autoDismiss) {
        setupAutoDismiss(alertElement, DEFAULT_OPTIONS.duration!);
      }
    }
  });
}

/**
 * Create and display a new alert dynamically from JavaScript.
 *
 * @param message - The message to display (can include HTML)
 * @param type - The alert type (success, error, warning, info, debug)
 * @param options - Optional configuration:
 *   - canDismiss: Show dismiss button (default: true)
 *   - autoDismiss: Enable auto-dismiss timer (default: true)
 *   - duration: Auto-dismiss duration in ms (default: 5000)
 */
export function showAlert(
  message: string,
  type: AlertType = 'info',
  options: AlertOptions = {}
): void {
  const opts = { ...DEFAULT_OPTIONS, ...options };

  // Get or create the alerts container
  let alertsContainer = document.querySelector('._cls-alerts') as HTMLElement;
  if (!alertsContainer) {
    alertsContainer = document.createElement('div');
    alertsContainer.className = '_cls-alerts';

    // Insert at the top of the main content area
    const mainElement = document.querySelector('._cls-main');
    if (mainElement) {
      mainElement.insertBefore(alertsContainer, mainElement.firstChild);
    } else {
      document.body.insertBefore(alertsContainer, document.body.firstChild);
    }
  }

  // Create the alert structure
  const alertContainer = document.createElement('div');
  alertContainer.className = '_cls-alert';

  const alertElement = document.createElement('div');
  alertElement.className = `alert-${type} _cls-fadeIn`;

  // Add data-auto-dismiss attribute if auto-dismiss is enabled
  if (opts.autoDismiss) {
    alertElement.setAttribute('data-auto-dismiss', '');
  }

  const iconSpan = document.createElement('span');
  iconSpan.className = '_cls-alertIcon';

  const messageSpan = document.createElement('span');
  messageSpan.className = '_cls-middleAlign';
  messageSpan.innerHTML = message;

  alertElement.appendChild(iconSpan);
  alertElement.appendChild(messageSpan);

  // Add dismiss button if canDismiss
  if (opts.canDismiss) {
    const closeSpan = document.createElement('span');
    closeSpan.className = '_cls-close';
    closeSpan.setAttribute('data-dismiss', 'alert');
    closeSpan.textContent = 'Dismiss';
    closeSpan.addEventListener('click', (e) => {
      e.preventDefault();
      dismissAlert(closeSpan);
    });
    alertElement.appendChild(closeSpan);
  }

  alertContainer.appendChild(alertElement);
  alertsContainer.appendChild(alertContainer);

  // Remove fade-in class after animation completes
  alertElement.addEventListener('animationend', (e) => {
    if ((e.target as HTMLElement) === alertElement && alertElement.classList.contains('_cls-fadeIn')) {
      alertElement.classList.remove('_cls-fadeIn');
    }
  }, { once: true });

  // Set up auto-dismiss if enabled
  if (opts.autoDismiss && opts.duration) {
    setupAutoDismiss(alertElement, opts.duration);
  }
}

/**
 * Dismiss an alert with animation.
 *
 * @param target - The dismiss button element or the alert element itself
 */
export function dismissAlert(target: HTMLElement): void {
  // Find the alert element (div with class alert-*)
  let alertElement: HTMLElement | null = null;

  if (target.className.startsWith('alert-')) {
    alertElement = target;
  } else {
    alertElement = target.closest('div[class^="alert-"]') as HTMLElement;
  }

  if (!alertElement) return;

  // Find the container (_cls-alert)
  const alertContainer = alertElement.parentElement;
  if (!alertContainer) return;

  // Clean up any timers and event listeners
  const cleanup = alertCleanups.get(alertElement);
  if (cleanup) {
    cleanup();
    alertCleanups.delete(alertElement);
  }

  // Add dismiss class to trigger animation
  alertElement.classList.add('_cls-dismiss');

  // Wait for animation to complete before removing
  alertElement.addEventListener('animationend', () => {
    alertContainer.remove();

    // Check if the alerts container is now empty
    const alertsContainer = document.querySelector('._cls-alerts');
    if (alertsContainer && alertsContainer.children.length === 0) {
      alertsContainer.remove();
    }
  }, { once: true });
}

/**
 * Set up auto-dismiss for an alert element.
 * Pauses on hover to allow reading.
 *
 * @param alertElement - The alert div element
 * @param duration - Time in milliseconds before auto-dismissing
 */
function setupAutoDismiss(alertElement: HTMLElement, duration: number): void {
  let timeoutId: number | null = null;
  let remainingTime = duration;
  let startTime = Date.now();

  const startTimer = () => {
    startTime = Date.now();
    timeoutId = window.setTimeout(() => {
      dismissAlert(alertElement);
    }, remainingTime);
  };

  const pauseTimer = () => {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
      remainingTime -= Date.now() - startTime;
      timeoutId = null;
    }
  };

  const resumeTimer = () => {
    if (remainingTime > 0) {
      startTimer();
    }
  };

  // Pause auto-dismiss on hover
  alertElement.addEventListener('mouseenter', pauseTimer);
  alertElement.addEventListener('mouseleave', resumeTimer);

  // Start the initial timer
  startTimer();

  // Store cleanup function
  alertCleanups.set(alertElement, () => {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
      timeoutId = null;
    }
    alertElement.removeEventListener('mouseenter', pauseTimer);
    alertElement.removeEventListener('mouseleave', resumeTimer);
  });
}
