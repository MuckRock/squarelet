// import CSS for bundling
import "@/css/team_list_item.css";
import "@/css/user_detail.css";

document.addEventListener('DOMContentLoaded', function() {
  function closeDropdown(container) {
    container.classList.remove('dropdown-open');
    container.setAttribute('data-dropdown-open', 'false');
  }

  var containers = document.querySelectorAll('.dropdown-container');
  containers.forEach(function(container) {
    var anchor = container.querySelector('.dropdown-anchor');
    if (anchor) {
      anchor.addEventListener('click', function(e) {
        e.preventDefault();
        var open = container.classList.contains('dropdown-open');
        if (open) {
          closeDropdown(container);
        } else {
          // Close all other dropdowns first
          containers.forEach(function(other) {
            if (other !== container) {
              closeDropdown(other);
            }
          });
          container.classList.add('dropdown-open');
          container.setAttribute('data-dropdown-open', 'true');
        }
      });
      // Ensure closed by default
      closeDropdown(container);
    }
  });

  // Close dropdown if clicking outside
  document.addEventListener('click', function(e) {
    containers.forEach(function(container) {
      if (!container.contains(e.target as Node)) {
        closeDropdown(container);
      }
    });
  });
});

// Tab controller/Tab container logic
document.querySelectorAll('.tab-controller').forEach(function(controller) {
  var container = controller.closest('.dropdown').querySelector('.tab-container');
  if (!container) return;

  function activateTab(tabName) {
    // Update controller tabs
    controller.querySelectorAll('.tab').forEach(function(tab) {
      var isActive = tab.getAttribute('data-tab') === tabName;
      tab.setAttribute('data-tab-active', String(isActive));
      tab.classList.toggle('tab-active', isActive);
    });
    // Update container tabs
    container.querySelectorAll('.tab').forEach(function(tab) {
      var isActive = tab.getAttribute('data-tab') === tabName;
      tab.setAttribute('data-tab-active', String(isActive));
      tab.classList.toggle('tab-active', isActive);
    });
  }

  // Click handler for controller tabs
  controller.querySelectorAll('.tab').forEach(function(tab) {
    tab.addEventListener('click', function(e) {
      e.preventDefault();
      var tabName = tab.getAttribute('data-tab');
      activateTab(tabName);
    });
  });

  // Initialize to first active tab
  var initial = controller.querySelector('.tab[data-tab-active="true"]');
  if (initial) {
    activateTab(initial.getAttribute('data-tab'));
  }
});