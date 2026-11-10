/* Opens Razorpay Checkout. Kept out of the template so the page needs no inline script. */
(function () {
  "use strict";
  var options = JSON.parse(document.getElementById("rzp-options").textContent);
  var returnUrl = JSON.parse(document.getElementById("rzp-return").textContent);
  // The return page only shows status. Publishing happens when Razorpay's webhook arrives.
  options.handler = function () { window.location.href = returnUrl; };
  document.getElementById("rzp-pay").addEventListener("click", function () {
    var checkout = new Razorpay(options);
    checkout.on("payment.failed", function () { window.location.href = returnUrl; });
    checkout.open();
  });
})();
