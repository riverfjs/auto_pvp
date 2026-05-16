RLQ.push([
  "jquery",
  () => {
    $(document).ready(function () {
      const typeList = [
        "普通",
        "草",
        "火",
        "水",
        "光",
        "地",
        "冰",
        "龙",
        "电",
        "毒",
        "虫",
        "武",
        "翼",
        "萌",
        "幽",
        "恶",
        "机械",
        "幻",
        "无",
      ];
      const typeEffectChart = {
        普通: { strong: [""], resist: ["地", "幽", "机械"], weak: ["武"], vulnerable: ["幽"] },
        草: {
          strong: ["水", "光", "地"],
          resist: ["火", "龙", "毒", "虫", "翼", "机械"],
          weak: ["火", "冰", "毒", "虫", "翼"],
          vulnerable: ["水", "地", "电", "光"],
        },
        火: {
          strong: ["草", "冰", "虫", "机械"],
          resist: ["水", "地", "龙"],
          weak: ["水", "地"],
          vulnerable: ["草", "冰", "虫", "萌", "机械"],
        },
        水: {
          strong: ["火", "地", "机械"],
          resist: ["草", "冰", "龙"],
          weak: ["草", "电"],
          vulnerable: ["火", "机械"],
        },
        光: { strong: ["幽", "恶"], resist: ["草", "冰"], weak: ["草", "幽"], vulnerable: ["恶", "幻"] },
        地: {
          strong: ["火", "冰", "电", "毒"],
          resist: ["草", "武"],
          weak: ["草", "水", "冰", "武", "机械"],
          vulnerable: ["普通", "火", "电", "毒", "翼"],
        },
        冰: {
          strong: ["草", "地", "龙", "翼"],
          resist: ["火", "冰", "机械"],
          weak: ["火", "地", "武", "机械"],
          vulnerable: ["水", "冰", "光"],
        },
        龙: { strong: ["龙"], resist: ["机械"], weak: ["冰", "龙", "萌"], vulnerable: ["草", "火", "水", "电", "翼"] },
        电: { strong: ["水", "翼"], resist: ["草", "地", "龙", "电"], weak: ["地"], vulnerable: ["电", "翼", "机械"] },
        毒: {
          strong: ["草", "萌"],
          resist: ["地", "毒", "幽", "机械"],
          weak: ["地", "恶", "幻"],
          vulnerable: ["草", "毒", "虫", "武", "萌"],
        },
        虫: {
          strong: ["草", "恶", "幻"],
          resist: ["火", "毒", "武", "翼", "萌", "幽", "机械"],
          weak: ["火", "翼"],
          vulnerable: ["草", "武"],
        },
        武: {
          strong: ["普通", "地", "冰", "恶", "机械"],
          resist: ["毒", "虫", "翼", "萌", "幽", "幻"],
          weak: ["翼", "萌", "幻"],
          vulnerable: ["地", "虫", "恶"],
        },
        翼: {
          strong: ["草", "虫", "武"],
          resist: ["地", "龙", "电", "机械"],
          weak: ["冰", "电"],
          vulnerable: ["草", "虫", "武"],
        },
        萌: {
          strong: ["龙", "武", "恶"],
          resist: ["火", "毒", "机械"],
          weak: ["毒", "恶", "机械"],
          vulnerable: ["虫", "武"],
        },
        幽: {
          strong: ["光", "幽", "幻"],
          resist: ["普通", "恶"],
          weak: ["光", "幽", "恶"],
          vulnerable: ["普通", "毒", "虫", "武"],
        },
        恶: {
          strong: ["毒", "萌", "幽"],
          resist: ["光", "武", "恶"],
          weak: ["光", "虫", "武", "萌"],
          vulnerable: ["幽", "恶"],
        },
        机械: {
          strong: ["地", "冰", "萌"],
          resist: ["火", "水", "电", "机械"],
          weak: ["火", "水", "武"],
          vulnerable: ["普通", "草", "冰", "龙", "毒", "虫", "翼", "萌", "机械", "幻"],
        },
        幻: { strong: ["毒", "武"], resist: ["光", "机械", "幻"], weak: ["虫", "幽"], vulnerable: ["武", "幻"] },
      };

      const typeIconMap = {
        普通: "https://patchwiki.biligame.com/images/rocom/6/69/nc77midbqeafn7i2snh5a5h16ctdi0o.png",
        草: "https://patchwiki.biligame.com/images/rocom/1/12/b8bsilucec9a98rsmqkmxt06c4mnnix.png",
        火: "https://patchwiki.biligame.com/images/rocom/a/ab/8wvxz3p479e2b702afdqyzhx9340qgx.png",
        水: "https://patchwiki.biligame.com/images/rocom/d/d1/csqsyhq1k488329455xdlzdcybv6zjh.png",
        光: "https://patchwiki.biligame.com/images/rocom/d/de/pxfi7cg0j94c45uxf4itigu90wis7jr.png",
        地: "https://patchwiki.biligame.com/images/rocom/3/32/0w5pybmkd8qm306doqx8kh5onl1o8cq.png",
        冰: "https://patchwiki.biligame.com/images/rocom/9/9b/oxnxxud1xhopw87c7mnawxijz8r1hns.png",
        龙: "https://patchwiki.biligame.com/images/rocom/6/65/kgcg0hvl19o7up0ug8f42bbvhi71dke.png",
        电: "https://patchwiki.biligame.com/images/rocom/0/02/iqzkamzcra945jsw5z6o8h9p30fv7db.png",
        毒: "https://patchwiki.biligame.com/images/rocom/5/53/jnd3vijasgthdz2ukggyfpisd464r2v.png",
        虫: "https://patchwiki.biligame.com/images/rocom/c/cb/q3mlwj270f67spwr934hpqx7hj62bm3.png",
        武: "https://patchwiki.biligame.com/images/rocom/5/52/q9hbq9nrnhjt7t86hy7sftv3e2e5fvx.png",
        翼: "https://patchwiki.biligame.com/images/rocom/2/2b/p7wdw88ziupp84s1mr8t9t602psswzz.png",
        萌: "https://patchwiki.biligame.com/images/rocom/5/5f/80jhk99eosjv1ld26wp7ljtmif27lfv.png",
        幽: "https://patchwiki.biligame.com/images/rocom/e/e7/ttqdi3zlz72g5dgmc8qg9ko4aorwllw.png",
        恶: "https://patchwiki.biligame.com/images/rocom/3/3b/hrdmz7n0qt3bnmir9fdn7977fvleec0.png",
        机械: "https://patchwiki.biligame.com/images/rocom/a/ad/fw81a2pvdickbcnq5rt17m6066cchcf.png",
        幻: "https://patchwiki.biligame.com/images/rocom/6/64/89miqle961qdw2tt56hb78bps6f34ci.png",
        无: "https://patchwiki.biligame.com/images/rocom/b/b2/nlbok7r3ok0qyeq73mlwh7hk84bmu2b.png",
      };

      function setTypeIconToBefore(selector) {
        $(selector).each(function () {
          var type = $(this).attr("data-type");
          var url = typeIconMap[type] || "";
          this.style.setProperty("--type-icon-url", url ? `url('${url}')` : "none");

          $(this).css("--type-icon-url", url ? `url('${url}')` : "none");

          var styleSheet = document.getElementById("typeicon-dyn-style");
          if (!styleSheet) {
            styleSheet = document.createElement("style");
            styleSheet.id = "typeicon-dyn-style";
            document.head.appendChild(styleSheet);
          }
          var cls = ".rocom_result_item";
          if ($(this).hasClass("rocom_type_select_btn")) {
            cls = ".rocom_type_select_btn";
          } else if ($(this).hasClass("rocom_restrainCalc_button")) {
            cls = ".rocom_restrainCalc_button";
          }
          var typeVal = type ? type.replace(/[^\w\u4e00-\u9fa5]/g, "") : "";
          var rule = `${cls}[data-type="${type}"]::before{background-image:${url ? `url('${url}')` : "none"};}`;

          var rules = styleSheet.innerHTML
            .split("\n")
            .filter((r) => !r.includes(`${cls}[data-type="${type}"]::before`));
          rules.push(rule);
          styleSheet.innerHTML = rules.join("\n");
        });
      }

      function closeTypeMenus() {
        $(".rocom_restrainCalc_button").removeClass("is-open");
      }

      function setTypeSelectorValue(button, type) {
        const buttonElement = $(button);
        buttonElement.attr("data-type", type);
        buttonElement.find(".rocom_restrainCalc_button_label").text(type);
      }

      function rebuildTypeSelectorOptions(buttonElement, availableTypes) {
        const menu = buttonElement.find(".rocom_restrainCalc_menu");
        menu.empty();

        availableTypes.forEach((type) => {
          const icon = typeIconMap[type] || "";
          const option = $(
            `<button type="button" class="rocom_restrainCalc_option" data-type="${type}">
                        <img src="${icon}" alt="${type}">
                        <span class="rocom_restrainCalc_option_text">${type}</span>
                    </button>`,
          );
          menu.append(option);
        });
      }

      function buildTypeSelector(button, initialType) {
        const buttonElement = $(button);
        const label = $('<span class="rocom_restrainCalc_button_label"></span>');
        const arrow = $('<span class="rocom_restrainCalc_button_arrow">▼</span>');
        const menu = $('<div class="rocom_restrainCalc_menu"></div>');

        buttonElement.empty().append(label, arrow, menu);
        rebuildTypeSelectorOptions(buttonElement, typeList);
        setTypeSelectorValue(buttonElement, initialType);
      }

      function syncSubTypeOptionsWithMain() {
        const mainVal = $(".rocom_restrainCalc_mainType .rocom_restrainCalc_button").attr("data-type");
        const subButton = $(".rocom_restrainCalc_subType .rocom_restrainCalc_button");
        const availableSubTypes = typeList.filter((type) => type === "无" || type !== mainVal);

        rebuildTypeSelectorOptions(subButton, availableSubTypes);

        const currentSubVal = subButton.attr("data-type") || "无";
        if (currentSubVal === mainVal) {
          setTypeSelectorValue(subButton, "无");
        }
      }

      const strongLabelHtml =
        '<span class="rocom_restrainCalc_result_title">造成伤害增加<i style="color: #4FBD72; font-style: normal;">⬆</i></span>';
      const resistLabelHtml =
        '<span class="rocom_restrainCalc_result_title">造成伤害降低<i style="color: #C4945A; font-style: normal;">⬇</i></span>';
      const weakLabelHtml =
        '<span class="rocom_restrainCalc_result_title">受到伤害增加<i style="color: #C4945A; font-style: normal;">⬆</i></span>';
      const vulnerableLabelHtml =
        '<span class="rocom_restrainCalc_result_title">受到伤害降低<i style="color: #4FBD72; font-style: normal;">⬇</i></span>';

      const specialTitleMap = {
        草: { text: "寄生", color: "#4FBD72", template: "免疫{word}" },
        火: { text: "灼烧", color: "#E86A3A", template: "免疫{word}" },
        毒: { text: "中毒", color: "#8E62D9", template: "免疫{word}" },
        冰: { text: "冻结", color: "#49A6E9", template: "免疫{word}" },
      };

      function updateRestrianTitle(mainType, subType) {
        const titleEl = $(".rocom_restrainCalc_title");
        const selectedTypes = [mainType, subType];
        const typeOrder = ["草", "火", "毒", "冰"];
        const matched = typeOrder.filter((type) => selectedTypes.includes(type));

        if (matched.length === 0) {
          titleEl.text("双属性默认不展示克制和被抵抗效果");
          return;
        }

        const clauses = matched.map((type) => {
          const config = specialTitleMap[type];
          const coloredWord = `<i style="color: ${config.color}; font-style: normal;">${config.text}</i>`;
          return config.template.replace("{word}", coloredWord);
        });

        titleEl.html(`这个系别搭配的精灵${clauses.join("、")}`);
      }

      function updateTypeEffectResult(mainType) {
        let subType = $(".rocom_restrainCalc_subType .rocom_restrainCalc_button").attr("data-type") || "无";
        let resultDivs = $(".rocom_restrainCalc_result");

        updateRestrianTitle(mainType, subType);

        if (!typeEffectChart[mainType] || subType === "无" || !typeEffectChart[subType]) {
          let chart = typeEffectChart[mainType];
          if (!chart) {
            resultDivs.eq(0).html(strongLabelHtml);
            resultDivs.eq(1).html(resistLabelHtml);
            resultDivs.eq(2).html(weakLabelHtml);
            resultDivs.eq(3).html(vulnerableLabelHtml);
            return;
          }
          let strongArr = chart.strong.filter((x) => x.length > 0);
          let resistArr = chart.resist.filter((x) => x.length > 0);
          let weakArr = chart.weak.filter((x) => x.length > 0);
          let vulnerableArr = chart.vulnerable.filter((x) => x.length > 0);
          function genResultHtml(arr, valueColor, value) {
            if (arr.length === 0)
              return `<div class='rocom_restrainCalc_result_list'><div class='rocom_result_item' data-type="无"><p class='rocom_result_item_name'>无</p></div></div>`;
            return `<div class='rocom_restrainCalc_result_list'>${arr
              .map(
                (type) =>
                  `<div class='rocom_result_item' data-type="${type}"><p class='rocom_result_item_name'>${type}系</p><span class='rocom_result_item_value' style='color:${valueColor};'>${value}</span></div>`,
              )
              .join("")}</div>`;
          }
          resultDivs.eq(0).html(strongLabelHtml + genResultHtml(strongArr, "#4FBD72", "2.0"));
          resultDivs.eq(1).html(resistLabelHtml + genResultHtml(resistArr, "#C4945A", "0.5"));
          resultDivs.eq(2).html(weakLabelHtml + genResultHtml(weakArr, "#C4945A", "2.0"));
          resultDivs.eq(3).html(vulnerableLabelHtml + genResultHtml(vulnerableArr, "#4FBD72", "0.5"));
          setTypeIconToBefore(".rocom_result_item");
          setTypeIconToBefore(".rocom_restrainCalc_button");
          return;
        }

        let mainChart = typeEffectChart[mainType];
        let subChart = typeEffectChart[subType];
        let weakCombined = mainChart.weak.concat(subChart.weak).filter((x) => x);
        let vulnerableCombined = mainChart.vulnerable.concat(subChart.vulnerable).filter((x) => x);

        function buildTypeItems(combined, singleValue, overlapValue) {
          let typeCount = {};
          let typeOrder = [];
          combined.forEach((type) => {
            if (!typeCount[type]) {
              typeOrder.push(type);
              typeCount[type] = 0;
            }
            typeCount[type] += 1;
          });

          return typeOrder.map((type, index) => ({
            type,
            count: typeCount[type],
            value: typeCount[type] > 1 ? overlapValue : singleValue,
            index,
          }));
        }

        let weakItems = buildTypeItems(weakCombined, "2.0", "3.0");
        let vulnerableItems = buildTypeItems(vulnerableCombined, "0.5", "0.25");
        const weakTypeSet = new Set(weakItems.map((item) => item.type));
        const vulnerableTypeSet = new Set(vulnerableItems.map((item) => item.type));
        const cancelTypeSet = new Set([...weakTypeSet].filter((type) => vulnerableTypeSet.has(type)));

        weakItems = weakItems
          .filter((item) => !cancelTypeSet.has(item.type))
          .sort((a, b) => b.count - a.count || a.index - b.index);
        vulnerableItems = vulnerableItems
          .filter((item) => !cancelTypeSet.has(item.type))
          .sort((a, b) => b.count - a.count || a.index - b.index);

        function genResultHtmlByItems(items, valueColor) {
          if (items.length === 0)
            return `<div class='rocom_restrainCalc_result_list'><div class='rocom_result_item' data-type="无"><p class='rocom_result_item_name'>无</p></div></div>`;
          return `<div class='rocom_restrainCalc_result_list'>${items
            .map(
              (item) =>
                `<div class='rocom_result_item' data-type="${item.type}"><p class='rocom_result_item_name'>${item.type}系</p><span class='rocom_result_item_value' style='color:${valueColor};'>${item.value}</span></div>`,
            )
            .join("")}</div>`;
        }

        function genResultHtml(arr, valueColor, value) {
          if (arr.length === 0)
            return `<div class='rocom_restrainCalc_result_list'><div class='rocom_result_item' data-type="无"><p class='rocom_result_item_name'>无</p></div></div>`;
          return `<div class='rocom_restrainCalc_result_list'>${arr
            .map(
              (type) =>
                `<div class='rocom_result_item' data-type="${type}"><p class='rocom_result_item_name'>${type}系</p><span class='rocom_result_item_value' style='color:${valueColor};'>${value}</span></div>`,
            )
            .join("")}</div>`;
        }
        resultDivs.eq(0).html(strongLabelHtml + genResultHtml([], "#4FBD72", "2.0"));
        resultDivs.eq(1).html(resistLabelHtml + genResultHtml([], "#C4945A", "0.5"));
        resultDivs.eq(2).html(weakLabelHtml + genResultHtmlByItems(weakItems, "#C4945A"));
        resultDivs.eq(3).html(vulnerableLabelHtml + genResultHtmlByItems(vulnerableItems, "#4FBD72"));
        setTypeIconToBefore(".rocom_result_item");
        setTypeIconToBefore(".rocom_restrainCalc_button");
      }

      let mainVal = $(".rocom_restrainCalc_mainType .rocom_restrainCalc_button").attr("data-type");
      updateTypeEffectResult(mainVal);

      $(".rocom_restrainCalc_layer").remove();
      $(document).off("click", ".rocom_type_select_btn");

      $(".rocom_restrainCalc_button").each(function () {
        if ($(this).closest(".rocom_restrainCalc_mainType").length) {
          buildTypeSelector(this, "普通");
        } else if ($(this).closest(".rocom_restrainCalc_subType").length) {
          buildTypeSelector(this, "无");
        }
      });

      syncSubTypeOptionsWithMain();

      setTypeIconToBefore(".rocom_restrainCalc_button");
      const initialMainVal = $(".rocom_restrainCalc_mainType .rocom_restrainCalc_button").attr("data-type");
      updateTypeEffectResult(initialMainVal);

      $(document).on("click", ".rocom_restrainCalc_button", function (event) {
        if ($(event.target).closest(".rocom_restrainCalc_menu").length) {
          return;
        }
        const buttonElement = $(this);
        const isOpen = buttonElement.hasClass("is-open");
        closeTypeMenus();
        if (!isOpen) {
          buttonElement.addClass("is-open");
        }
      });

      $(document).on("click", ".rocom_restrainCalc_option", function (event) {
        event.stopPropagation();
        const selectedType = $(this).attr("data-type");
        const parentDiv = $(this).closest(".rocom_restrainCalc_button");
        setTypeSelectorValue(parentDiv, selectedType);

        if (parentDiv.closest(".rocom_restrainCalc_mainType").length) {
          syncSubTypeOptionsWithMain();
        }

        closeTypeMenus();
        setTypeIconToBefore(".rocom_restrainCalc_button");
        const mainVal = $(".rocom_restrainCalc_mainType .rocom_restrainCalc_button").attr("data-type");
        updateTypeEffectResult(mainVal);
      });

      $(document).on("click", function (event) {
        if ($(event.target).closest(".rocom_restrainCalc_button").length === 0) {
          closeTypeMenus();
        }
      });
    });
  },
]);
