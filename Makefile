PY ?= ./.venv/bin/python

.PHONY: venv test doctor udev clean

venv:
	python3 -m venv .venv
	./.venv/bin/pip -q install --upgrade pip pyusb

test:
	$(PY) tests/test_protocol.py

doctor:
	$(PY) uc1810c.py doctor

udev:
	sudo install -m644 99-presonus-1810c.rules /etc/udev/rules.d/
	sudo udevadm control --reload
	sudo udevadm trigger --action=add --subsystem-match=usb

clean:
	rm -rf __pycache__ tests/__pycache__
