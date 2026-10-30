# 大肥鱼数据备份 20261031-0420
解密: age -d -i fatfish_age_identity.txt fatfish-data-20261031-0420.tar.gz.age.age > fatfish-data-20261031-0420.tar.gz.age
还原: tar xzf fatfish-data-20261031-0420.tar.gz.age 后按内部相对路径盖回 / 原位置, 再重启 astrbot 与 snowluma
若被拆分为 part 文件: cat *.part-* | cat > fatfish-data-20261031-0420.tar.gz.age 先合并再解密
sha256 校验文件: fatfish-data-20261031-0420.tar.gz.age.sha256 (对合并解密后的包校验)
