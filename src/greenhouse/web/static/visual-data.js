function svgNode(tag, attributes, label) {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    if (label !== undefined) element.textContent = text(label);
    return element;
}

function figure(target, width, height) {
    const svg = svgNode('svg', {viewBox:`0 0 ${width} ${height}`, role:'img', 'aria-label':target.dataset.axis});
    target.append(svg);
    return svg;
}

function drawProjectChart(target, points) {
    const svg = figure(target, 680, 260);
    if (!points.length) return;
    const low = Math.min(0,...points.map(i=>i.value));
    const high = Math.max(1,...points.map(i=>i.value));
    const spacing = 586 / Math.max(1, points.length - 1);
    const coordinates = points.map((entry,i)=>[42+spacing*i,219-(entry.value-low)/(high-low)*173]);
    for (let y=48;y<=219;y+=42) svg.append(svgNode('line',{x1:40,x2:645,y1:y,y2:y,class:'chart-grid'}));
    const values = coordinates.map(([x,y])=>`${x},${y}`).join(' ');
    svg.append(svgNode('polygon',{points:`42,219 ${values} ${coordinates.at(-1)[0]},219`,class:'water-area'}));
    svg.append(svgNode('polyline',{points:values,class:'series-line'}));
    coordinates.forEach(([x,y],i)=> {
        const pin=svgNode('circle',{cx:x,cy:y,r:4,class:'chart-dot'});
        pin.append(svgNode('title',{},`${points[i].label} ${text(points[i].value)}`));
        svg.append(pin);
        if (i % 3 === 0) svg.append(svgNode('text',{x,y:245,class:'chart-caption'},points[i].label.slice(0,8)));
    });
}
