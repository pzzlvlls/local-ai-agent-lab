from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode


async def parse_image_block(image_block: BlockNode) -> None:
    image_block.payload = {"token": image_block.content}
    image_block.content = f"图片token: {image_block.content}"
