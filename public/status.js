(async function () {
  const el = document.getElementById('status');
  const text = document.getElementById('status-text');
  const stats = document.getElementById('stats');
  const ticker = document.getElementById('ticker');

  const topics = [
    "neural sde", "stochastic differential equation", "neural cde",
    "controlled differential equation", "rough volatility", "fractional brownian motion",
    "volatility surface", "implied volatility", "local volatility",
    "stochastic volatility", "volatility indices", "vix", "vvix", "vxn",
    "derivatives pricing", "options pricing", "arbitrage free modeling",
    "term structure modeling", "time series representation learning",
    "contrastive learning", "self supervised learning", "financial time series",
    "transformer time series", "sequence modeling", "latent variable models",
    "representation learning", "score based models", "diffusion models",
    "generative models time series", "stochastic control",
    "reinforcement learning trading", "optimal execution", "market microstructure",
    "limit order book", "statistical arbitrage", "alpha signals",
    "alpha generation", "regime detection", "state space models",
    "hidden markov models", "manifold learning", "clustering financial data",
    "optimal transport finance", "information geometry", "game theory finance",
    "quantitative finance theory"
  ];

  // Populate ticker twice for seamless scrolling
  if (ticker) {
    const content = topics.map(t => `<span>${t}</span>`).join('');
    ticker.innerHTML = content + content;
  }

  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    if (d.status === 'active') {
      el.className = 'status active';
      text.textContent = 'Active';
      document.getElementById('papers').textContent = d.total_papers.toLocaleString();
      document.getElementById('ideas').textContent = d.total_ideas.toLocaleString();
      stats.classList.add('visible');
    } else {
      throw new Error();
    }
  } catch {
    el.className = 'status error';
    text.textContent = 'Unreachable';
  }
})();
