# Django
import hashlib
import random

from django import template

register = template.Library()

def deterministic_hash(s):
  return int(hashlib.sha1(s.encode('ascii')).hexdigest(), 16) % (10 ** 8)

def make_code(id_value, seed, size=45):
  return '''
<script>
var m_w = 123456789;
var m_z = 987654321;
var mask = 0xffffffff;

function hash(s) {
  var hash = 0, i, chr;
  if (s.length === 0) return hash;
  for (i = 0; i < s.length; i++) {
    chr   = s.charCodeAt(i);
    hash  = ((hash << 5) - hash) + chr;
    hash |= 0; // Convert to 32bit integer
  }
  return hash;
}

// Takes any integer
function seed(i) {
    m_w = (123456789 + i) & mask;
    m_z = (987654321 - i) & mask;
}

// Returns number between 0 (inclusive) and 1.0 (exclusive),
// just like Math.random().
function random()
{
    m_z = (36969 * (m_z & 65535) + (m_z >> 16)) & mask;
    m_w = (18000 * (m_w & 65535) + (m_w >> 16)) & mask;
    var result = ((m_z << 16) + (m_w & 65535)) >>> 0;
    result /= 4294967296;
    return result;
}

var sample = function(l) {
  return l[Math.floor(random() * l.length)];
}

function componentToHex(c) {
    var hex = c.toString(16);
    return hex.length == 1 ? "0" + hex : hex;
}

function rgbToHex(r, g, b) {
    return "#" + componentToHex(r) + componentToHex(g) + componentToHex(b);
}

var getComponent = function(c) {
  if (c <= 10) {
    return c / 3294;
  } else {
    return Math.pow(c / 269 + 0.0513, 2.4);
  }
};

var getLuminance = function(color) {
  return 0.2126 * getComponent(color[0]) + 0.7152 * getComponent(color[1]) + 0.0722 * getComponent(color[2]);
};

var getContrast = function(l1, l2) {
  if (l1 > l2) {
    return (l1 + 0.05) / (l2 + 0.05);
  } else {
    return (l2 + 0.05) / (l1 + 0.05);
  }
}

var getColor = function() {
  var getRGBValue = function() {
    return Math.floor(random() * 256);
  }
  return [getRGBValue(), getRGBValue(), getRGBValue()];
}

var background = [200, 200, 200];
var backgroundLuminance = getLuminance(background);

var getHighContrast = function() {
  var contrast = 0;
  var color = null;
  while (contrast < 1.5) {
    color = getColor();
    var luminance = getLuminance(color);
    contrast = getContrast(luminance, backgroundLuminance);
  }
  return [color, contrast];
}

var getRandColor = function() {
  var contrastInfo = getHighContrast();
  return rgbToHex(contrastInfo[0][0], contrastInfo[0][1], contrastInfo[0][2]);
//   var colorChoices = ['#F2C57C', '#7EDDDC', '#7FB685', '#EF6F6C', '#7E3F8F'];
//   return sample(colorChoices);
}


var background = 'White';

function createSVG(id, randomSeed, size) {
  var elem = document.getElementById(id);
  seed(randomSeed);

  var svgSpec = 'http://www.w3.org/2000/svg';
  var svg = document.createElementNS(svgSpec, 'svg');
  var width = size;
  var height = size;
  
  
  
  svg.setAttribute('width', width);
  svg.setAttribute('height', width);

  var $a = '' + (size / 6) + ' ';
  var $b = '' + (size / 4) + ' ';
  var $c = '' + (size / 2 + size / 12) + ' ';

  var viewBoxes = [$a + $a + $b + $b, $c + $c + $b + $b];
  // / var viewBoxes = ['10 10 15 15', '35 35 15 15'];
  
  // svg.setAttribute('viewBox', sample(viewBoxes));
  $a = '' + (size * 0.1) + ' ';
  $b = '' + (size * 0.9 - $a) + ' ';
  svg.setAttribute('viewBox', $a + $a + $b + $b);
  var midX = width / 2;
  var midY = height / 2;

  // var midpoint = document.createElementNS(svgSpec, 'circle');
  // midpoint.setAttribute('fill', 'blue');
  // midpoint.setAttribute('cx', midX);
  // midpoint.setAttribute('cy', midY);
  // midpoint.setAttribute('r', 10);
  // svg.appendChild(midpoint);

  var boundingBox = document.createElementNS(svgSpec, 'rect');
  boundingBox.setAttribute('x', 0);
  boundingBox.setAttribute('y', 0);
  boundingBox.setAttribute('width', width);
  boundingBox.setAttribute('height', height);
  boundingBox.setAttribute('fill', sample(['rgb(240,200,200)','rgb(200,240,200)','rgb(200,200,240)', 'rgb(240,240,200)', 'rgb(240,200,240)', 'rgb(200,240,240)']));
  boundingBox.setAttribute('stroke', 'black');
  boundingBox.setAttribute('stroke-width', 1);
  svg.appendChild(boundingBox);

  var symmetries = [4, 5, 7, 9, 11];
  var symmetry = sample(symmetries);
  var degrees = 360 / symmetry;
  var safeMaxDiameter = size / 2;
  var safeMinDiameter = size / 6;
  var safeMaxSize = size / 6;
  var safeMinSize = size / 15;

//   var colors = ['red', 'blue', 'green', 'yellow', 'pink', 'cyan', 'transparent'];

  var rotateAllAround = function(elem) {
    for (var i = 1; i < symmetry; i++) {
      var newElem = elem.cloneNode();
      var rotation = 'rotate(' + (degrees * i) + ', ' + midX + ', ' + midY + ')';
      newElem.setAttribute('transform', rotation);
      svg.appendChild(newElem);
    }
  }

  var getRand = function() {
    if (random() < 0.5) {
      return random() / 3 + 1;
    } else {
      return -random() / 3 - 1;
    }
  }

  var createRect = function() {
    var rect = document.createElementNS(svgSpec, 'rect');
    var fill = Math.floor(random() * 2);
    if (fill) {
      rect.setAttribute('fill', getRandColor());
    } else {
      rect.setAttribute('fill', 'none');
      rect.setAttribute('stroke', getRandColor());
      rect.setAttribute('stroke-width', (safeMinSize + random() * (safeMaxSize - safeMinSize)) / 4);
    }

    rect.setAttribute('x', getRand() * safeMinDiameter + midX);
    rect.setAttribute('y', getRand() * safeMinDiameter + midY);
    rect.setAttribute('width', safeMinSize + random() * (safeMaxSize - safeMinSize));
    rect.setAttribute('height', safeMinSize + random() * (safeMaxSize - safeMinSize));
    svg.appendChild(rect);
    rotateAllAround(rect);
  }

  var createCircle = function() {
    var circle = document.createElementNS(svgSpec, 'circle');
    circle.setAttribute('fill', getRandColor());
    circle.setAttribute('cx', getRand() * safeMinDiameter + midX);
    circle.setAttribute('cy', getRand() * safeMinDiameter + midY);
    circle.setAttribute('r', (safeMinSize + random() * (safeMaxSize - safeMinSize)) / 2);
    svg.appendChild(circle);
    rotateAllAround(circle);
  }

  /** create symmetry stuff */
  var fns = [createRect, createCircle];
  for (var i = 0; i < 5; i++) {
    sample(fns)();
  }

  elem.appendChild(svg);
}  
''' + 'createSVG("%s", %d, %d);\n' % (id_value, seed, size) + '''
</script>
'''

@register.simple_tag
def avatar(s, size=45):
  id_value = 'avatar%d' % random.randint(0, 10000000)
  seed = deterministic_hash(s)
  return '<div class="_cls-avatar" id="%s"></div>%s' % (id_value, make_code(id_value, seed, size))


#   random.seed(deterministic_hash(s))

#   def component_to_hex(c) {
#     return '#%02x%02x%02x' % c
#   }

#   def getComponent(c):
#     if c <= 10:
#       return c / 3294
#     else:
#       return Math.pow(c / 269 + 0.0513, 2.4)

#   def getLuminance(color):
#     return 0.2126 * getComponent(color[0]) + 0.7152 * getComponent(color[1]) + 0.0722 * getComponent(color[2]);
# };

# var getContrast = function(l1, l2) {
#   if (l1 > l2) {
#     return (l1 + 0.05) / (l2 + 0.05);
#   } else {
#     return (l2 + 0.05) / (l1 + 0.05);
#   }
# }

# var getColor = function() {
#   var getRGBValue = function() {
#     return Math.floor(Math.random() * 256);
#   }
#   return [getRGBValue(), getRGBValue(), getRGBValue()];
# }

# var background = [200, 200, 200];
# var backgroundLuminance = getLuminance(background);

# var getHighContrast = function() {
#   var contrast = 0;
#   var color = null;
#   while (contrast < 1.5) {
#     color = getColor();
#     var luminance = getLuminance(color);
#     contrast = getContrast(luminance, backgroundLuminance);
#   }
#   return [color, contrast];
# }

# var getRandColor = function() {
#   var contrastInfo = getHighContrast();
#   return rgbToHex(contrastInfo[0][0], contrastInfo[0][1], contrastInfo[0][2]);
# //   var colorChoices = ['#F2C57C', '#7EDDDC', '#7FB685', '#EF6F6C', '#7E3F8F'];
# //   return sample(colorChoices);
# }


# var background = 'White';

# function createSVG() {
#   var svgSpec = 'http://www.w3.org/2000/svg';
#   var svg = document.createElementNS(svgSpec, 'svg');
#   var size = 60;
#   var width = size;
#   var height = size;
  
  
  
#   svg.setAttribute('width', width);
#   svg.setAttribute('height', width);

#   var viewBoxes = ['10 10 15 15', '35 35 15 15'];
  
#   svg.setAttribute('viewBox', sample(viewBoxes));
#   var midX = width / 2;
#   var midY = height / 2;

#   // var midpoint = document.createElementNS(svgSpec, 'circle');
#   // midpoint.setAttribute('fill', 'blue');
#   // midpoint.setAttribute('cx', midX);
#   // midpoint.setAttribute('cy', midY);
#   // midpoint.setAttribute('r', 10);
#   // svg.appendChild(midpoint);

#   var boundingBox = document.createElementNS(svgSpec, 'rect');
#   boundingBox.setAttribute('x', 0);
#   boundingBox.setAttribute('y', 0);
#   boundingBox.setAttribute('width', width);
#   boundingBox.setAttribute('height', height);
#   boundingBox.setAttribute('fill', sample(['rgb(240,200,200)','rgb(200,240,200)','rgb(200,200,240)', 'rgb(240,240,200)', 'rgb(240,200,240)', 'rgb(200,240,240)']));
#   boundingBox.setAttribute('stroke', 'black');
#   boundingBox.setAttribute('stroke-width', 1);
#   svg.appendChild(boundingBox);

#   var symmetries = [4, 5, 7, 9, 11];
#   var symmetry = sample(symmetries);
#   var degrees = 360 / symmetry;
#   var safeMaxDiameter = size / 2;
#   var safeMinDiameter = size / 6;
#   var safeMaxSize = size / 6;
#   var safeMinSize = size / 15;

# //   var colors = ['red', 'blue', 'green', 'yellow', 'pink', 'cyan', 'transparent'];

#   var rotateAllAround = function(elem) {
#     for (var i = 1; i < symmetry; i++) {
#       var newElem = elem.cloneNode();
#       var rotation = 'rotate(' + (degrees * i) + ', ' + midX + ', ' + midY + ')';
#       newElem.setAttribute('transform', rotation);
#       svg.appendChild(newElem);
#     }
#   }

#   var getRand = function() {
#     if (Math.random() < 0.5) {
#       return Math.random() / 3 + 1;
#     } else {
#       return -Math.random() / 3 - 1;
#     }
#   }

#   var createRect = function() {
#     var rect = document.createElementNS(svgSpec, 'rect');
#     var fill = Math.floor(Math.random() * 2);
#     if (fill) {
#       rect.setAttribute('fill', getRandColor());
#     } else {
#       rect.setAttribute('fill', 'none');
#       rect.setAttribute('stroke', getRandColor());
#       rect.setAttribute('stroke-width', (safeMinSize + Math.random() * (safeMaxSize - safeMinSize)) / 4);
#     }

#     rect.setAttribute('x', getRand() * safeMinDiameter + midX);
#     rect.setAttribute('y', getRand() * safeMinDiameter + midY);
#     rect.setAttribute('width', safeMinSize + Math.random() * (safeMaxSize - safeMinSize));
#     rect.setAttribute('height', safeMinSize + Math.random() * (safeMaxSize - safeMinSize));
#     svg.appendChild(rect);
#     rotateAllAround(rect);
#   }

#   var createCircle = function() {
#     var circle = document.createElementNS(svgSpec, 'circle');
#     circle.setAttribute('fill', getRandColor());
#     circle.setAttribute('cx', getRand() * safeMinDiameter + midX);
#     circle.setAttribute('cy', getRand() * safeMinDiameter + midY);
#     circle.setAttribute('r', (safeMinSize + Math.random() * (safeMaxSize - safeMinSize)) / 2);
#     svg.appendChild(circle);
#     rotateAllAround(circle);
#   }

#   /** create symmetry stuff */
#   var fns = [createRect, createCircle];
#   for (var i = 0; i < 5; i++) {
#     sample(fns)();
#   }

#   document.body.appendChild(svg);
# }  
# for (var j = 0; j < 500; j++) {
#   createSVG();
# }
