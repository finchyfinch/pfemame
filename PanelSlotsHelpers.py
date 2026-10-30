# PanelSlotsHelpers.py
#
# Helper class for PanelSlots.py
#
# NOTE: MAME XML output is not fully XML-compliant, so all parsing uses manual string
# splitting rather than a standard XML parser.


class SlotDataParser:
    """Parses MAME -listxml output (as a list of lines) for a specific ROM."""

    def __init__(self, lines: list[str], rom_name: str):
        self.lines = lines
        self.rom_name = rom_name
        self.slot_names, self.slot_names_subset, self.bios_names, self.bios_descriptions = self._parse()

    # ------------------------------------------------------------------------------------------------------------------
    def _parse(self) -> tuple[list[str], list[str], list[str], list[str]]:
        """Extract slot names and BIOS info for this ROM from the XML lines."""
        slot_names = ['']
        slot_names_subset = []
        bios_names = ['']
        bios_descriptions = ['']
        machine_tag = f'machine name="{self.rom_name}"'

        for index, line in enumerate(self.lines):
            if machine_tag in line:
                for line in self.lines[index:]:
                    if '</machine>' in line:
                        break  # End of machine block
                    elif 'biosset' in line:
                        bios_names.append(line.split('name="')[1].split('"')[0])
                        bios_descriptions.append(line.split('description="')[1].split('"')[0])
                    elif 'slot name' in line:
                        slot_name = line.split('"')[1]
                        slot_names.append(slot_name)
                        slot_names_subset.append(slot_name.split(':')[0])
                break  # Found and processed the desired machine block
        else:
            print('Error: machine not found in XML output')

        # Convert to sets to remove duplicates
        slot_names = sorted(list(set(slot_names)))
        slot_names_subset = list(set(slot_names_subset))

        return slot_names, slot_names_subset, bios_names, bios_descriptions

    # ------------------------------------------------------------------------------------------------------------------
    def get_machine_start_index(self, rom_name: str) -> int:
        """Return the line index where the given machine block begins, or -1 if not found."""
        for index, line in enumerate(self.lines):
            if f'machine name="{rom_name}"' in line:
                return index
        return -1

    # ------------------------------------------------------------------------------------------------------------------
    def get_default_device_info(self, slot_name: str) -> tuple[list[str], str | None, str | None]:
        """
        Find all device names for a slot and identify the default one.

        Returns:
            (device_names_for_slot, default_device_name, short_name)
            or ([], None, None) if not found.
        """
        in_machine = False
        in_slot = False
        device_names_for_slot = []
        default_device_name = None
        short_name = None

        for line in self.lines:
            if f'<machine name="{self.rom_name}"' in line:
                in_machine = True
                continue

            if in_machine and '<machine' in line and self.rom_name not in line:
                # Entering a different machine block
                break

            if in_machine and f'<slot name="{slot_name}"' in line:
                in_slot = True
                continue

            if in_slot:
                if '</slot>' in line:
                    break  # Finished this slot block

                if '<slotoption ' in line:
                    try:
                        parts = line.split('"')
                        name = parts[1]
                        devname = parts[3]
                        device_names_for_slot.append(devname)

                        if 'default="yes"' in line:
                            default_device_name = devname
                            short_name = name
                    except IndexError:
                        continue  # Malformed line

        return device_names_for_slot, default_device_name, short_name

    # ------------------------------------------------------------------------------------------------------------------
    def find_device_names(
            self,
            slot_name: str,
            parent_name: str = '',
            slot_option: str = ''
    ) -> list[str]:
        """
        Find device names from slot options in the XML lines.

        Args:
            slot_name: Name of the slot to search for.
            parent_name: Optional parent machine name to narrow search scope.
            slot_option: If provided, return only this device name (as a single-element list).

        Returns:
            A sorted list of device names. Returns [''] if nothing is found.
        """
        results = ['']

        # Validate inputs
        if not slot_name:
            return results
        if slot_option == '':
            slot_option = None  # Easier logic later

        # Find parent machine start index if specified
        start_index = next(
            (i for i, line in enumerate(self.lines)
             if parent_name and f'machine name="{parent_name}"' in line),
            0
        )

        # Find slot index
        slot_index = next(
            (i for i, line in enumerate(self.lines[start_index:], start=start_index)
             if f'slot name="{slot_name}"' in line),
            None
        )

        if slot_index is None:
            print('There may be something wrong with this INI file.')
            return results

        # Find the start of the slot options for this slot name
        slot_option_start_index = slot_index + 1
        for index, line in enumerate(self.lines[slot_index + 1:]):
            if f'slot name="{slot_name}"' in line:
                slot_option_start_index = slot_index + 1 + index
                break

        # Search for slot options
        for line in self.lines[slot_option_start_index:]:
            if '</slot>' in line:
                break
            if 'slotoption name=' in line:
                parts = line.split('"')
                if len(parts) > 3:
                    name = parts[3]
                    if slot_option:
                        if f'<slotoption name="{slot_option}"' in line:  # Closing quote: exact match, not prefix
                            return [name]  # Return single result
                    else:
                        results.append(name)
        return sorted(results)
