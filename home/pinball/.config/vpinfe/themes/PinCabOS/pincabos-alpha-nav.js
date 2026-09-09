// PINCABOS_ALPHA_MAGNASAVE_NAV_V1
// Theme-only alphabet navigation for VPinFE paging inputs.
// Left Magna  -> joypageup   -> prev -> previous available letter.
// Right Magna -> joypagedown -> next -> next available letter.
(() => {
    const core = window.vpin;

    if (!core || typeof core.getPageIndex !== "function") {
        console.warn("PinCabOS Alpha Nav: VPinFE paging API unavailable");
        return;
    }

    if (core.__pincabosAlphaNavInstalled) {
        return;
    }

    const nativeGetPageIndex = core.getPageIndex.bind(core);

    function getTableTitle(index) {
        try {
            const table = core.getTableMeta(index);
            const info = table?.meta?.Info || {};
            const vpx = table?.meta?.VPXFile || {};

            return String(
                info.Title ||
                vpx.filename ||
                table?.tableDirName ||
                ""
            ).trim();
        } catch (error) {
            console.debug("PinCabOS Alpha Nav: unable to read table metadata", index, error);
            return "";
        }
    }

    function getTableInitial(index) {
        const title = getTableTitle(index);
        if (!title) {
            return "";
        }

        const normalized = title
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .trim()
            .toUpperCase();

        const match = normalized.match(/[A-Z]/);
        return match ? match[0] : "";
    }

    function buildFirstTableByLetter() {
        const firstByLetter = new Map();
        const tableCount = Array.isArray(core.tableData)
            ? core.tableData.length
            : 0;

        for (let index = 0; index < tableCount; index += 1) {
            const letter = getTableInitial(index);

            if (letter && !firstByLetter.has(letter)) {
                firstByLetter.set(letter, index);
            }
        }

        return firstByLetter;
    }

    async function getAlphaPageIndex(direction, currentIndex) {
        if (direction !== "prev" && direction !== "next") {
            return nativeGetPageIndex(direction, currentIndex);
        }

        const firstByLetter = buildFirstTableByLetter();
        const currentLetter = getTableInitial(currentIndex);

        if (!currentLetter || firstByLetter.size < 2) {
            return nativeGetPageIndex(direction, currentIndex);
        }

        const letters = Array.from(firstByLetter.keys()).sort();
        let targetLetter = "";

        if (direction === "next") {
            targetLetter = letters.find((letter) => letter > currentLetter) || letters[0];
        } else {
            for (let index = letters.length - 1; index >= 0; index -= 1) {
                if (letters[index] < currentLetter) {
                    targetLetter = letters[index];
                    break;
                }
            }

            if (!targetLetter) {
                targetLetter = letters[letters.length - 1];
            }
        }

        const targetIndex = firstByLetter.get(targetLetter);

        if (typeof targetIndex !== "number" || targetIndex < 0) {
            return nativeGetPageIndex(direction, currentIndex);
        }

        console.debug(
            `PinCabOS Alpha Nav: ${currentLetter} -> ${targetLetter}`,
            { direction, currentIndex, targetIndex }
        );

        return targetIndex;
    }

    core.getPageIndex = getAlphaPageIndex;
    core.__pincabosAlphaNavInstalled = true;

    console.log("PinCabOS Alpha Nav: Magna Save alphabet navigation enabled");
})();
