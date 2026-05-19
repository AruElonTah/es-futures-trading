npx playwright evaluate --browser chromium http://localhost:3000/dashboard "async () => {
  // Wait for data
  await new Promise(r => setTimeout(r, 8000));
  
  const canvases = document.querySelectorAll('canvas');
  const info = [...canvases].map((c, i) => ({
    index: i,
    width: c.width,
    height: c.height,
    offsetWidth: c.offsetWidth,
    offsetHeight: c.offsetHeight,
    parentHeight: c.parentElement?.clientHeight,
    rect: JSON.stringify(c.getBoundingClientRect())
  }));
  
  return JSON.stringify(info, null, 2);
}"
