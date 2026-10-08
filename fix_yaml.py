import os
path1 = '.github/workflows/ci.yml'
with open(path1, 'r') as f:
    c = f.read()
c = c.replace('actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11', 'actions/checkout@v4')
c = c.replace('actions/setup-python@0b9330426db129596324ab5296831d163fbab9ee', 'actions/setup-python@v5')
c = c.replace('astral-sh/setup-uv@0b9330426db129596324ab5296831d163fbab9ee', 'astral-sh/setup-uv@v3')
c = c.replace('actions/setup-node@b4ffde65f46336ab88eb53be808477a3936bae11', 'actions/setup-node@v4')
with open(path1, 'w') as f:
    f.write(c)

path2 = '.github/workflows/dependency-review.yml'
with open(path2, 'r') as f:
    c = f.read()
c = c.replace('actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11', 'actions/checkout@v4')
c = c.replace('actions/dependency-review-action@b4ffde65f46336ab88eb53be808477a3936bae11', 'actions/dependency-review-action@v4')
with open(path2, 'w') as f:
    f.write(c)
