/* Deployment History Page JavaScript. */

function initializePage() {
  const timeRangeSelect = document.getElementById('time-range-select');
  const customDateRange = document.getElementById('custom-date-range');
  const perPageSelect = document.getElementById('per-page-select');

  initializeTimeRangeFilter(timeRangeSelect, customDateRange);
  initializePerPageSelector(perPageSelect);
  initializeTableEffects();
  initializeFormHandlers();
  addPulseAnimation();
}

function initializeTimeRangeFilter(timeRangeSelect, customDateRange) {
  if (!timeRangeSelect || !customDateRange) return;

  function toggleCustomDateRange() {
    if (timeRangeSelect.value === 'custom') {
      customDateRange.classList.add('show');
    } else {
      customDateRange.classList.remove('show');
    }
  }

  toggleCustomDateRange();

  timeRangeSelect.addEventListener('change', toggleCustomDateRange);
}

function initializePerPageSelector(perPageSelect) {
  if (!perPageSelect) return;

  perPageSelect.addEventListener('change', function () {
    const currentUrl = new URL(window.location);
    currentUrl.searchParams.set('per_page', this.value);
    currentUrl.searchParams.set('page', '1'); // Reset to first page when changing per_page
    window.location.href = currentUrl.toString();
  });
}

function initializeTableEffects() {
  const tableRows = document.querySelectorAll('tbody tr');
  tableRows.forEach(row => {
    row.addEventListener('mouseenter', function () {
      this.style.boxShadow = '0 4px 15px rgba(102, 126, 234, 0.2)';
    });

    row.addEventListener('mouseleave', function () {
      this.style.boxShadow = 'none';
    });
  });
}

function initializeFormHandlers() {
  const filterForm = document.getElementById('filter-form');
  if (filterForm) {
    filterForm.addEventListener('submit', function () {
      const pageInput = this.querySelector('input[name="page"]');
      if (pageInput) {
        pageInput.value = '1';
      }
    });
  }
}

function addPulseAnimation() {
  const style = document.createElement('style');
  style.textContent = `
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.1); }
            100% { transform: scale(1); }
        }
        
        .loading {
            animation: pulse 1s ease-in-out infinite;
        }
    `;
  document.head.appendChild(style);
}

document.addEventListener('DOMContentLoaded', initializePage);
