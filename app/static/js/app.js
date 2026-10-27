(() => {
  const root = document.documentElement;
  const storedTheme = localStorage.getItem("fdr-theme");
  const systemTheme = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  root.dataset.theme = storedTheme || systemTheme;

  const toggle = document.getElementById("theme-toggle");
  toggle?.addEventListener("click", () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("fdr-theme", root.dataset.theme);
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  const form = document.querySelector("[data-fdr-form]");
  if (!form) return;
  const amount = form.elements.principal;
  const rate = form.elements.interest_rate;
  const start = form.elements.start_date;
  const maturity = form.elements.maturity_date;
  const output = document.getElementById("estimate-value");
  const updateEstimate = () => {
    const principal = Number(amount.value);
    const annualRate = Number(rate.value);
    const startDate = new Date(`${start.value}T00:00:00`);
    const endDate = new Date(`${maturity.value}T00:00:00`);
    if (!principal || !Number.isFinite(annualRate) || !start.value || !maturity.value || endDate < startDate) {
      output.textContent = "Enter amount, rate and valid dates";
      return;
    }
    const days = Math.round((endDate - startDate) / 86400000);
    const estimated = principal * (1 + annualRate / 100 * days / 365);
    output.textContent = `₹${estimated.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} · ${days} days`;
  };
  [amount, rate, start, maturity].forEach((input) => input.addEventListener("input", updateEstimate));
  updateEstimate();
})();
