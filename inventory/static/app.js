(() => {
  const button = document.querySelector(".nav-toggle");
  const navigation = document.querySelector("#site-navigation");
  if (!button || !navigation) return;

  const close = () => {
    navigation.classList.remove("is-open");
    button.setAttribute("aria-expanded", "false");
  };

  button.addEventListener("click", () => {
    const open = navigation.classList.toggle("is-open");
    button.setAttribute("aria-expanded", String(open));
  });

  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) close();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      close();
      button.focus();
    }
  });
})();


